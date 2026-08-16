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


def worker_zip() -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(WORKER_MANIFEST))
        archive.writestr("worker.js", WORKER)
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
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": worker_zip(), "granted": WORKER_MANIFEST["permissions"]}
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
