"""Engine simulation: fairness, frame dedup, standby gating, the watchdog
and the command protocol, all against an in-memory platform."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fakes import FakePlatform

from printguard.engine import watchdog
from printguard.engine.engine import Engine

OCTOPRINT = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}


@asynccontextmanager
async def running_engine(platform: FakePlatform, camera_fps: list[float]):
    """Starts an engine with one monitor per camera and guarantees stop()."""
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)
    for fps in camera_fps:
        await engine.handle({"cmd": "camera.add", "name": f"cam{fps}", "source": {"kind": "fake", "fps": fps}})
    for camera in engine.cameras.values():
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": f"m-{camera.name}", "camera_id": camera.id}})
    try:
        yield engine, events
    finally:
        await engine.stop()


async def _register_printer(engine: Engine) -> str:
    """Registers an OctoPrint printer and returns its id."""
    await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
    return next(iter(engine.printers.items))


async def test_fair_allocation_and_dedup() -> None:
    platform = FakePlatform(infer_s=0.05)
    async with running_engine(platform, camera_fps=[30.0, 10.0, 3.0]) as (engine, events):
        seen: dict[str, list[float]] = {}
        original = engine.scheduler._on_result

        async def spy(camera, frame, result):
            seen.setdefault(camera.id, []).append(frame.seq)
            await original(camera, frame, result)

        engine.scheduler._on_result = spy
        await asyncio.sleep(5.0)
        names = {camera.id: camera.name for camera in engine.cameras.values()}
        capacity = engine.scheduler.capacity_fps()

    # Generous bands: shared CI runners skew wall-clock timing, and a
    # required merge check must not flake. The exact invariants (dedup,
    # ordering, fairness direction) stay strict.
    assert 8.0 < capacity < 30.0, f"capacity estimate off: {capacity}"
    by_name = {names[cid]: seqs for cid, seqs in seen.items()}
    for seqs in seen.values():
        assert seqs == sorted(set(seqs)), "a frame was inferred twice or out of order"
    slow_rate = len(by_name["cam3.0"]) / 5.0
    fast_rate = len(by_name["cam30.0"]) / 5.0
    mid_rate = len(by_name["cam10.0"]) / 5.0
    assert 1.5 <= slow_rate <= 3.5, f"slow camera should run near native rate, got {slow_rate}"
    assert fast_rate > slow_rate, "surplus capacity should flow to the fast camera"
    assert abs(fast_rate - mid_rate) < 4.0, f"fast/mid should share fairly: {fast_rate} vs {mid_rate}"


async def test_defect_pipeline() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {
                "cmd": "settings.update",
                "patch": {
                    "notifiers": {
                        "ntfy": {"url": "http://ntfy/topic"},
                        "telegram": {"bot_token": "t", "chat_id": "1"},
                        "discord": {"webhook_url": "http://disc/hook"},
                    }
                },
            }
        )
        printer_id = await _register_printer(engine)
        await engine.handle(
            {"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True, "printer_id": printer_id, "on_defect": "pause"}}
        )
        await asyncio.sleep(2.0)
        state_monitors = engine.state_event()["monitors"]

    alerts = [e for e in events if e.get("event") == "alert"]
    assert alerts, "no alert emitted for sustained defect"
    assert alerts[0]["action"] == "pause", f"expected pause action, got {alerts[0]}"
    assert any("/api/job" in url for _, url in platform.http_calls), "OctoPrint pause was never sent"
    results = [e for e in events if e.get("event") == "result"]
    assert results and all(r["prediction"] == "failure" for r in results)
    assert state_monitors[0]["alert"], "alert missing from state"
    assert ("PUT", "http://ntfy/topic") in platform.http_calls, "ntfy alert was never delivered"
    assert any("api.telegram.org" in url and url.endswith("/sendPhoto") for _, url in platform.http_calls), "Telegram alert was never delivered"
    assert ("POST", "http://disc/hook") in platform.http_calls, "Discord alert was never delivered"


async def test_standby_gating() -> None:
    watchdog.DEVICE_POLL_S = 0.1
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(1.0)
        assert not engine.state_event()["monitors"][0]["watching"], "idle printer should be in standby"
        assert not engine.cameras.schedulable(), "standby monitor's camera should not be scheduled"
        results_during_standby = len([e for e in events if e.get("event") == "result"])

        platform.device_status = "Printing"
        await asyncio.sleep(1.0)
        assert engine.state_event()["monitors"][0]["watching"], "printing printer should be watched"
        resumed = len([e for e in events if e.get("event") == "result"]) - results_during_standby
    assert resumed > 0, "inference did not resume when printing started"


async def test_watchdog_and_failed_action() -> None:
    watchdog.DEVICE_POLL_S = 0.1
    watchdog.WATCH_TICK_S = 0.05
    watchdog.OFFLINE_GRACE_S = 0.2
    watchdog.ACT_RETRY_S = 0.01
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.reject_actions = True
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        printer_id = await _register_printer(engine)
        await engine.handle(
            {"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True, "printer_id": printer_id, "on_defect": "pause"}}
        )
        await asyncio.sleep(1.0)
        alerts = [e for e in events if e.get("event") == "alert"]
        assert alerts and alerts[0]["action"] == "failed", f"rejected pause should surface as failed, got {alerts}"
        errors = [e for e in events if e.get("event") == "error"]
        assert any("pause failed" in e["message"] for e in errors), "failed action did not emit an error event"

        camera = next(iter(engine.cameras.values()))
        camera.frame_source.online = False
        await asyncio.sleep(0.6)
        warnings = [e for e in events if e.get("event") == "warning" and not e["recovered"]]
        assert any("offline" in w["message"] for w in warnings), "camera outage did not warn"
        assert any(url == "http://ntfy/topic" for _, url in platform.http_calls), "outage warning was not pushed to notifiers"

        camera.frame_source.online = True
        await asyncio.sleep(0.3)
    recoveries = [e for e in events if e.get("event") == "warning" and e["recovered"]]
    assert any("back" in r["message"] for r in recoveries), "camera recovery was not announced"


async def test_protocol_surfaces_errors_and_filters_settings() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "nope", "req_id": 7})
        assert any(e["event"] == "error" and "unknown command" in e["message"] for e in events)

        await engine.handle({"cmd": "monitor.update", "id": "missing", "patch": {}, "req_id": 8})
        assert any(e["event"] == "error" and e.get("req_id") == 8 for e in events)

        await engine.handle({"cmd": "settings.update", "patch": {"bogus": 1, "notifiers": {"ntfy": {"url": "u"}}}})
        assert "bogus" not in engine.settings
        assert engine.settings["notifiers"] == {"ntfy": {"url": "u"}}


async def test_provider_change_clears_stale_printer_state() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        engine.printers.get(printer_id).device_state = {"status": "printing", "progress": 1.0, "job": None}
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "Renamed"}})
        assert engine.printers.get(printer_id).device_state["status"] == "printing", "same provider must keep its state"

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://kl"}}})
        assert engine.printers.get(printer_id).device_state is None, "a new provider must not inherit the old state"


async def test_state_persists_across_restart() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": "Resurrected", "notify": True, "printer_id": printer_id}})

    reborn = Engine(platform)
    await reborn.start()
    try:
        assert [c.name for c in reborn.cameras.values()] == ["cam10.0"]
        restored = reborn.monitors[monitor_id]
        assert restored["name"] == "Resurrected"
        assert restored["notify"] is True
        assert restored["printer_id"] == printer_id
        printer = reborn.printers.get(printer_id)
        assert printer and printer.name == "P" and printer.provider == "octoprint"
    finally:
        await reborn.stop()
