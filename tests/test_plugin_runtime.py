"""The hub's plugin sandbox: what a worker can do, and what it cannot.

These run real JavaScript inside the shipped QuickJS WebAssembly build, so a
failure here means the sandbox itself has changed behaviour.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from contextlib import asynccontextmanager

import pytest
from fakes import FakePlatform

from printguard.engine.engine import Engine

OCTOPRINT = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}
from printguard.engine.registry import Plugin
from printguard.server.plugins import Sandbox, WasmPluginRuntime

CALL = {"kind": "event", "event": {"event": "alert", "score": 0.9}, "request": {}, "state": {}, "store": {}}


@pytest.fixture(scope="module")
def runtime() -> WasmPluginRuntime:
    return WasmPluginRuntime()


def make_plugin(code: str, granted: list[str] | None = None, permissions: list[str] | None = None) -> Plugin:
    manifest = {
        "id": "demo",
        "name": "Demo",
        "permissions": permissions if permissions is not None else (granted or []),
        "hosts": ["hooks.example.com"],
        "events": ["alert"],
        "tick_s": 0.0,
    }
    return Plugin(id="demo", manifest=manifest, sources={"worker.js": code}, digests={}, source={}, granted=granted or [])


def call(runtime: WasmPluginRuntime, code: str, payload: dict | None = None) -> dict:
    sandbox = Sandbox(runtime._engine, runtime._module, runtime._linker, make_plugin(code))
    return sandbox.call({**CALL, **(payload or {})})


def test_worker_handles_an_event_and_keeps_its_own_data(runtime: WasmPluginRuntime) -> None:
    output = call(
        runtime,
        "plugin.on('alert', (event, ctx) => { ctx.store.seen = (ctx.store.seen || 0) + 1; ctx.notify('at ' + event.score); });",
        {"store": {"seen": 2}},
    )

    assert output["store"] == {"seen": 3}
    assert output["effects"] == [{"kind": "notify", "text": "at 0.9"}]


def test_worker_that_never_finishes_is_cut_off(runtime: WasmPluginRuntime) -> None:
    with pytest.raises(RuntimeError):
        call(runtime, "plugin.on('alert', () => { while (true) {} });")


def test_worker_cannot_import_its_way_out(runtime: WasmPluginRuntime) -> None:
    """A worker runs inside a function, where import is a syntax error.

    QuickJS's std module can read stdin and write stdout, which is how the
    sandbox is spoken to, so a worker must never reach it.
    """
    with pytest.raises(RuntimeError, match="SyntaxError"):
        call(runtime, "import * as std from 'qjs:std'; plugin.on('alert', () => std.out.puts('mine'));")


def test_worker_has_no_filesystem_and_no_network(runtime: WasmPluginRuntime) -> None:
    output = call(
        runtime,
        """
        plugin.on('alert', (event, ctx) => {
          ctx.store.std = typeof std;
          ctx.store.os = typeof os;
          ctx.store.fetch = typeof fetch;
          ctx.store.require = typeof require;
        });
        """,
    )

    assert output["store"] == dict.fromkeys(("std", "os", "fetch", "require"), "undefined")


def test_worker_sees_only_the_state_it_was_granted(runtime: WasmPluginRuntime) -> None:
    output = call(
        runtime,
        "plugin.on('alert', (event, ctx) => { ctx.store.keys = Object.keys(ctx.state).sort(); });",
        {"state": {"monitors": [{"id": "m"}], "mode": "hub"}},
    )

    assert output["store"]["keys"] == ["mode", "monitors"]


async def test_effects_a_plugin_was_not_granted_are_refused(runtime: WasmPluginRuntime) -> None:
    performed: list[dict] = []
    runtime.attach(lambda command: _record(performed, command), lambda plugin_id, reason: None)
    plugin = make_plugin("", granted=["notify"], permissions=["notify", "printer:control"])

    await runtime._perform(
        plugin,
        [
            {"kind": "command", "cmd": {"cmd": "printer.action", "id": "p", "action": "pause"}},
            {"kind": "notify", "text": "allowed"},
        ],
    )

    assert [c["cmd"] for c in performed] == ["plugin.notify"], "an ungranted printer action was carried out"


def _record(sink: list[dict], command: dict) -> asyncio.Future:
    sink.append(command)
    done: asyncio.Future = asyncio.get_event_loop().create_future()
    done.set_result(None)
    return done


WORKER = """
plugin.on('alert', (event, ctx) => {
  ctx.store.last = event.score;
  ctx.command({ cmd: 'monitor.update', id: event.monitor_id, patch: { enabled: false } });
});
plugin.route((request, ctx) => ({ status: 200, type: 'text/plain', body: 'seen ' + (ctx.store.last || 0) }));
plugin.gate((request) => request.path !== '/secret');
"""

WORKER_MANIFEST = {
    "id": "guard",
    "name": "Guard",
    "version": "1.0.0",
    "permissions": ["monitor:control", "routes", "gate"],
    "events": ["alert"],
}


def bundle(manifest: dict, worker: str) -> str:
    """Packs a worker-only plugin the way an imported file arrives."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
        archive.writestr("worker.js", worker)
    return base64.b64encode(buffer.getvalue()).decode()


class HostedPlatform(FakePlatform):
    """A platform that carries a real plugin runtime, as the hub does."""

    def __init__(self, runtime: WasmPluginRuntime) -> None:
        super().__init__(infer_s=0.02)
        self.plugin_runtime = runtime


@asynccontextmanager
async def engine_with_worker(runtime: WasmPluginRuntime):
    engine = Engine(HostedPlatform(runtime))
    await engine.start()
    try:
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": bundle(WORKER_MANIFEST, WORKER), "granted": WORKER_MANIFEST["permissions"]}
        )
        yield engine
    finally:
        await engine.stop()


async def test_a_worker_reacts_to_an_alert_and_its_command_is_carried_out(runtime: WasmPluginRuntime) -> None:
    async with engine_with_worker(runtime) as engine:
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": "c"}})
        monitor_id = next(iter(engine.monitors))

        engine.emit({"event": "alert", "monitor_id": monitor_id, "score": 0.91, "action": "pause"})
        await asyncio.sleep(0.5)

        assert engine.monitors[monitor_id]["enabled"] is False, "the worker's granted command never ran"
        assert engine.plugins.get("guard").config == {"last": 0.91}, "the worker's own data was not kept"


async def test_a_worker_serves_its_routes_and_gates_requests(runtime: WasmPluginRuntime) -> None:
    async with engine_with_worker(runtime) as engine:
        engine.emit({"event": "alert", "monitor_id": "m", "score": 0.5, "action": "none"})
        await asyncio.sleep(0.4)

        answer = await runtime.serve("guard", {"method": "GET", "path": "/plugins/guard/", "query": {}, "headers": {}, "body": None})
        allowed = await runtime.authorise({"method": "GET", "path": "/", "query": {}, "headers": {}, "body": None})
        refused = await runtime.authorise({"method": "GET", "path": "/secret", "query": {}, "headers": {}, "body": None})

    assert answer["body"] == "seen 0.5"
    assert allowed is True and refused is False


async def test_a_plugin_that_fails_is_disabled_rather_than_left_running(runtime: WasmPluginRuntime) -> None:
    async with engine_with_worker(runtime) as engine:
        engine.plugins.get("guard").sources["worker.js"] = "plugin.on('alert', () => { while (true) {} });"
        await engine.handle({"cmd": "plugin.update", "id": "guard", "patch": {"enabled": True}})

        engine.emit({"event": "alert", "monitor_id": "m", "score": 0.5, "action": "none"})
        await asyncio.sleep(1.0)

        plugin = engine.plugins.get("guard")
        assert plugin.enabled is False and plugin.failure


async def test_a_worker_cannot_borrow_another_plugins_network_grant(runtime: WasmPluginRuntime) -> None:
    """A plugin names only itself on the way out.

    The request comes from inside the sandbox, so a plugin that could set the
    id on it would be checked against a *different* installed plugin's declared
    hosts, and exfiltrate through a grant it was never given.
    """
    performed: list[dict] = []
    runtime.attach(lambda command: _record(performed, command), lambda plugin_id, reason: None)
    plugin = make_plugin("", granted=["net"], permissions=["net"])

    await runtime._perform(
        plugin,
        [{"kind": "http", "request": {"id": "someone-else", "cmd": "printer.action", "url": "https://hooks.example.com/x"}}],
    )

    assert performed == [
        {"cmd": "plugin.http", "method": "GET", "url": "https://hooks.example.com/x", "headers": None, "json": None, "id": "demo"}
    ]


SNOOP_WORKER = """
plugin.on('state', (event, ctx) => { ctx.store.state = JSON.stringify(event); });
plugin.on('token_created', (event, ctx) => { ctx.store.token = event.token; });
"""

SNOOP_MANIFEST = {
    "id": "snoop",
    "name": "Snoop",
    "version": "1.0.0",
    "permissions": ["state:read"],
    "events": ["state", "token_created"],
}


async def test_a_worker_watching_events_sees_no_credentials(runtime: WasmPluginRuntime) -> None:
    """An engine event is projected before a plugin gets it.

    The snapshot carries printer credentials and the API token event carries a
    freshly minted secret, neither of which any permission grants.
    """
    engine = Engine(HostedPlatform(runtime))
    await engine.start()
    try:
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": bundle(SNOOP_MANIFEST, SNOOP_WORKER),
             "granted": ["state:read"]}
        )
        await engine.handle({"cmd": "token.create", "name": "t", "scope": "manage"})
        await asyncio.sleep(0.5)

        config = engine.plugins.get("snoop").config
        assert "token" not in config, "a plugin hooked an event it may not see"
        assert "api_key" not in config["state"] and "settings" not in config["state"]
    finally:
        await engine.stop()


RISK_WORKER = """
plugin.on('result', (event, ctx) => {
  if (event.score < (ctx.store.limit || 0.8)) return;
  ctx.store.hits = (ctx.store.hits || 0) + 1;
  if (ctx.store.hits === 1) ctx.command({ cmd: 'printer.action', id: ctx.store.printer, action: 'pause' });
});
"""

RISK_MANIFEST = {
    "id": "risk",
    "name": "Risk watch",
    "version": "1.0.0",
    "permissions": ["state:read", "printer:control"],
    "events": ["result"],
}


async def test_a_worker_can_act_on_a_single_inference_over_its_own_threshold(runtime: WasmPluginRuntime) -> None:
    """The per-inference hook: every score, before any streak logic applies."""
    platform = HostedPlatform(runtime)
    engine = Engine(platform)
    await engine.start()
    try:
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
        printer_id = next(iter(engine.printers.items))
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": bundle(RISK_MANIFEST, RISK_WORKER),
             "granted": RISK_MANIFEST["permissions"]}
        )
        await engine.handle({"cmd": "plugin.update", "id": "risk", "patch": {"config": {"limit": 0.8, "printer": printer_id}}})

        for score in (0.10, 0.55, 0.91, 0.95):
            engine.emit({"event": "result", "monitor_id": "m1", "camera_id": "c1", "score": score, "ts": 1.0})
            await asyncio.sleep(0.3)

        assert engine.plugins.get("risk").config["hits"] == 2, "scores under the plugin's own limit were acted on"
        assert [m for m, url in platform.http_calls if "/api/job" in url].count("POST") == 1, "the printer was not paused once"
    finally:
        await engine.stop()
