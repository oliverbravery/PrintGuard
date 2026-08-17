"""The hub's plugin sandbox, QuickJS compiled to WebAssembly under wasmtime.

A plugin's ``worker.js`` runs here as a pure function. Each invocation gets a
brand new JavaScript VM with the event, the state its permissions allow and its
own stored data on stdin, and returns its new data plus a list of effects on
stdout. PrintGuard performs the effects; the plugin performs none itself.

The instance has no preopened directories and no sockets, so there is no
filesystem and no network inside it whatever the code asks for, and it runs
against a memory cap and a CPU fuel budget, so a plugin that hangs or allocates
without bound traps in milliseconds and is disabled rather than taking the hub
with it. WASI's one blocking call is stubbed out, so nothing inside can wait:
without it, a sleeping plugin would sit in a host call where neither the fuel
budget nor an epoch deadline can reach it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import wasmtime

from ..engine import plugins
from ..engine.registry import Plugin

logger = logging.getLogger(__name__)

QJS_WASM = Path(__file__).parent / "runtime" / "qjs.wasm"
FUEL = 400_000_000
MEMORY_BYTES = 96 * 1024 * 1024
CALL_TIMEOUT_S = 5.0
MAX_OUTPUT_BYTES = 512 * 1024
MAX_EFFECTS = 32
ENOTSUP = 58

SHIM = """
import * as __io from "qjs:std";
const __input = JSON.parse(__io.in.readAsString());
const __effects = [];
const __hooks = { events: new Map(), route: null, gate: null };
const plugin = {
  on(name, fn) { __hooks.events.set(String(name), fn); },
  route(fn) { __hooks.route = fn; },
  gate(fn) { __hooks.gate = fn; },
};
const ctx = {
  store: __input.store,
  state: __input.state,
  command(cmd) { __effects.push({ kind: "command", cmd }); },
  http(request) { __effects.push({ kind: "http", request }); },
  notify(text) { __effects.push({ kind: "notify", text: String(text) }); },
  log(text) { __effects.push({ kind: "log", text: String(text) }); },
};
(function (plugin) {
"""

DRIVER = """
})(plugin);
let __result = null;
if (__input.kind === "event" || __input.kind === "tick") {
  const handler = __hooks.events.get(String(__input.event.event));
  if (handler) handler(__input.event, ctx);
} else if (__input.kind === "request" && __hooks.route) {
  __result = __hooks.route(__input.request, ctx);
} else if (__input.kind === "gate" && __hooks.gate) {
  __result = __hooks.gate(__input.request, ctx) === true;
}
__io.out.puts(JSON.stringify({ store: ctx.store, effects: __effects, result: __result }));
"""
"""The worker runs inside a function, so its own ``import`` is a syntax error
and QuickJS's std and os modules stay out of its reach. Without that it could
write to stdout, which is how the sandbox answers."""


class Sandbox:
    """One plugin's worker, instantiated fresh for every call."""

    def __init__(self, engine: wasmtime.Engine, module: wasmtime.Module, linker: wasmtime.Linker, plugin: Plugin) -> None:
        self._engine = engine
        self._module = module
        self._linker = linker
        self.plugin = plugin
        self.code = SHIM + plugin.sources["worker.js"] + DRIVER

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Runs the worker once and returns its parsed output.

        Raises:
            RuntimeError: If the sandbox trapped, timed out or wrote nothing
                a caller can read.
        """
        with tempfile.TemporaryDirectory() as work:
            paths = {name: Path(work) / name for name in ("in", "out", "err")}
            paths["in"].write_text(json.dumps(payload))
            paths["out"].touch()
            paths["err"].touch()
            wasi = wasmtime.WasiConfig()
            wasi.argv = ["qjs", "-e", self.code]
            wasi.stdin_file = str(paths["in"])
            wasi.stdout_file = str(paths["out"])
            wasi.stderr_file = str(paths["err"])
            store = wasmtime.Store(self._engine)
            store.set_wasi(wasi)
            store.set_fuel(FUEL)
            store.set_limits(memory_size=MEMORY_BYTES)
            try:
                self._linker.instantiate(store, self._module).exports(store)["_start"](store)
            except wasmtime.Trap as exc:
                raise RuntimeError(self._diagnose(paths["err"], exc)) from exc
            except wasmtime.ExitTrap as exc:
                if exc.code:
                    raise RuntimeError(self._diagnose(paths["err"], exc)) from exc
            output = paths["out"].read_bytes()
        if len(output) > MAX_OUTPUT_BYTES:
            raise RuntimeError(f"worker returned more than {MAX_OUTPUT_BYTES // 1024} KB")
        try:
            return json.loads(output)
        except ValueError as exc:
            raise RuntimeError("worker returned nothing usable") from exc

    @staticmethod
    def _diagnose(err: Path, exc: Exception) -> str:
        detail = err.read_text().strip().splitlines()
        if detail:
            return detail[0][:200]
        return "ran out of time or memory" if isinstance(exc, wasmtime.Trap) else str(exc)[:200]


class WasmPluginRuntime:
    """Runs every enabled plugin's worker and performs the effects they ask for."""

    def __init__(self) -> None:
        config = wasmtime.Config()
        config.consume_fuel = True
        self._engine = wasmtime.Engine(config)
        self._module = wasmtime.Module.from_file(self._engine, str(QJS_WASM))
        self._linker = wasmtime.Linker(self._engine)
        self._linker.allow_shadowing = True
        self._linker.define_wasi()
        i32 = wasmtime.ValType.i32()
        self._linker.define_func(
            "wasi_snapshot_preview1", "poll_oneoff", wasmtime.FuncType([i32] * 4, [i32]), lambda *_: ENOTSUP
        )
        self._sandboxes: dict[str, Sandbox] = {}
        self._request: Callable[..., Awaitable[Any]] | None = None
        self._failed: Callable[[str, str], None] | None = None
        self._state: dict[str, Any] = {}
        self._ticker: asyncio.Task[None] | None = None
        self._busy: set[str] = set()
        self._lock = asyncio.Lock()

    def attach(self, request: Callable[..., Awaitable[Any]], failed: Callable[[str, str], None]) -> None:
        """Takes the engine's command channel and failure report."""
        self._request = request
        self._failed = failed

    def on_event(self, event: dict[str, Any]) -> None:
        """Delivers an engine event to the plugins that asked to hear it.

        A worker still busy with the last one is skipped rather than queued
        behind it: result events run at several hertz per monitor, and a plugin
        slower than its own event rate would otherwise accumulate calls without
        bound.
        """
        if event.get("event") == "state":
            self._state = event
        for sandbox in list(self._sandboxes.values()):
            plugin = sandbox.plugin
            if event.get("event") not in plugin.manifest["events"] or plugin.id in self._busy:
                continue
            seen = plugins.project_event(event, plugin.granted)
            if seen:
                asyncio.ensure_future(self._invoke(sandbox, "event", event=seen))

    async def reload(self, running: list[Plugin]) -> None:
        """Starts sandboxes for plugins with a worker and drops the rest."""
        async with self._lock:
            wanted = {p.id: p for p in running if "worker.js" in p.sources}
            self._sandboxes = {
                plugin_id: Sandbox(self._engine, self._module, self._linker, plugin)
                for plugin_id, plugin in wanted.items()
            }
        if self._ticker is None:
            self._ticker = asyncio.ensure_future(self._tick())
        logger.info("plugin runtime holding %d worker(s)", len(self._sandboxes))

    async def serve(self, plugin_id: str, request: dict[str, Any]) -> dict[str, Any] | None:
        """Hands a request to a plugin's route handler."""
        sandbox = self._sandboxes.get(plugin_id)
        if sandbox is None or not sandbox.plugin.may("routes"):
            return None
        result = await self._invoke(sandbox, "request", request=request)
        return result if isinstance(result, dict) else None

    def gate_paths(self) -> tuple[str, ...]:
        """Finds the route prefixes belonging to the plugins that gate requests.

        Returns:
            One prefix per gating plugin. A gate is asked about every request
            except those, which stay open so the sign-in page a gate serves
            cannot be refused by itself.
        """
        return tuple(f"/plugins/{s.plugin.id}/" for s in self._sandboxes.values() if s.plugin.may("gate"))

    async def authorise(self, request: dict[str, Any]) -> bool | None:
        """Asks the gating plugin whether a request may proceed.

        A gate that fails to answer refuses, so a broken plugin cannot open the
        hub up. ``PRINTGUARD_PLUGINS=off`` is the way back in.
        """
        gates = [s for s in self._sandboxes.values() if s.plugin.may("gate")]
        if not gates:
            return None
        for sandbox in gates:
            if await self._invoke(sandbox, "gate", request=request) is not True:
                return False
        return True

    async def close(self) -> None:
        """Stops the timer and drops every sandbox."""
        if self._ticker is not None:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)
            self._ticker = None
        self._sandboxes.clear()

    async def _tick(self) -> None:
        last: dict[str, float] = {}
        while True:
            await asyncio.sleep(plugins.MIN_TICK_S)
            now = time.monotonic()
            for sandbox in list(self._sandboxes.values()):
                every = sandbox.plugin.manifest["tick_s"]
                if every and now - last.get(sandbox.plugin.id, 0.0) >= every:
                    last[sandbox.plugin.id] = now
                    await self._invoke(sandbox, "tick", event={"event": "tick"})

    async def _invoke(self, sandbox: Sandbox, kind: str, **payload: Any) -> Any:
        """Runs a worker off the event loop, then performs what it asked for."""
        plugin = sandbox.plugin
        request = {
            "kind": kind,
            "event": payload.get("event", {}),
            "request": payload.get("request", {}),
            "state": plugins.project_state(self._state, plugin.granted),
            "store": plugin.config,
        }
        self._busy.add(plugin.id)
        try:
            output = await asyncio.wait_for(asyncio.to_thread(sandbox.call, request), CALL_TIMEOUT_S)
        except Exception as exc:
            self._sandboxes.pop(plugin.id, None)
            if self._failed:
                self._failed(plugin.id, str(exc))
            logger.warning("plugin %s worker failed: %s", plugin.id, exc)
            return None
        finally:
            self._busy.discard(plugin.id)
        await self._store(plugin, output.get("store"))
        await self._perform(plugin, output.get("effects") or [])
        return output.get("result")

    async def _store(self, plugin: Plugin, store: Any) -> None:
        if not isinstance(store, dict) or store == plugin.config or self._request is None:
            return
        try:
            await self._request({"cmd": "plugin.update", "id": plugin.id, "patch": {"config": store}})
        except Exception as exc:
            logger.warning("plugin %s could not save its data: %s", plugin.id, exc)

    async def _perform(self, plugin: Plugin, effects: list[Any]) -> None:
        """Carries out a worker's effects, refusing any it was not granted."""
        if self._request is None:
            return
        for effect in effects[:MAX_EFFECTS]:
            kind = effect.get("kind") if isinstance(effect, dict) else None
            try:
                if kind == "command":
                    command = dict(effect["cmd"])
                    permission = plugins.PERMISSION_COMMANDS.get(str(command.get("cmd")))
                    if permission is None or not plugin.may(permission):
                        raise PermissionError(f"{command.get('cmd')!r} needs a permission this plugin was not granted")
                    await self._request(command)
                elif kind == "http":
                    await self._request(plugins.outbound_request(plugin.id, effect.get("request")))
                elif kind == "notify":
                    if not plugin.may("notify"):
                        raise PermissionError("this plugin was not granted notifications")
                    await self._request({"cmd": "plugin.notify", "id": plugin.id, "text": effect["text"]})
                elif kind == "log":
                    logger.info("plugin %s: %s", plugin.id, str(effect["text"])[:400])
            except Exception as exc:
                logger.warning("plugin %s effect %s refused: %s", plugin.id, kind, exc)
