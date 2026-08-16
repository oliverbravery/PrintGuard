"""The hub's plugin sandbox: what a worker can do, and what it cannot.

These run real JavaScript inside the shipped QuickJS WebAssembly build, so a
failure here means the sandbox itself has changed behaviour.
"""

from __future__ import annotations

import asyncio

import pytest

from printguard.engine.registry import Plugin
from printguard.server.plugins import Sandbox, WasmPluginRuntime

CALL = {"kind": "event", "event": {"event": "alert", "score": 0.9}, "request": {}, "state": {}, "store": {}, "config": {}, "now": 1.0}


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
