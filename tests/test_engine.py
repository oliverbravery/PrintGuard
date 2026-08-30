"""Engine simulation: fairness, frame dedup, standby gating, the watchdog
and the command protocol, all against an in-memory platform."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import zipfile
from urllib.parse import parse_qs, urlparse
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import numpy as np
import pytest
from fakes import FakePlatform

from printguard.engine import engine as engine_module
from printguard.engine import logs, oauth, plugins, reports, vision, watchdog
from printguard.engine.engine import EVENT_LOG_LEVELS, Engine
from printguard.engine.integrations import INTEGRATIONS

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
                        "pushover": {"api_token": "ap", "user_key": "uk"},
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
    assert ("POST", "https://api.pushover.net/1/messages.json") in platform.http_calls, "Pushover alert was never delivered"
    assert any(urlparse(url).hostname == "api.telegram.org" and url.endswith("/sendPhoto") for _, url in platform.http_calls), "Telegram alert was never delivered"
    assert ("POST", "http://disc/hook") in platform.http_calls, "Discord alert was never delivered"


async def test_alert_only_notification_wording() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True, "consecutive": 1}})
        await asyncio.sleep(1.0)

    request = next(request for request in platform.http_requests if request["url"] == "http://ntfy/topic")
    assert request["headers"]["Message"] == "Alert only: no printer action configured"


async def test_slow_printer_action_does_not_pause_inference(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "ACT_ATTEMPTS", 1)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", 0.2)
    platform = FakePlatform(infer_s=0.02)
    platform.action_delay_s = 0.4
    platform.reject_actions = True
    async with running_engine(platform, camera_fps=[30.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle(
            {
                "cmd": "monitor.update",
                "id": monitor_id,
                "patch": {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1},
            }
        )
        platform.failing = True
        await asyncio.wait_for(platform.action_started.wait(), 1.0)
        before = len([event for event in events if event.get("event") == "result"])
        await asyncio.sleep(0.3)
        after = len([event for event in events if event.get("event") == "result"])
        await asyncio.sleep(0.3)
        alerts = [event for event in events if event.get("event") == "alert"]

    assert after > before, "printer action I/O paused inference"
    assert alerts and alerts[0]["action"] == "failed", "failed printer action did not complete in the background"
    assert not any(event.get("event") == "warning" and "feed has stalled" in event["message"] for event in events)


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
        camera = engine.cameras.values()[0]
        assert camera.standby and not camera.online, "standby camera capture should sleep"
        results_during_standby = len([e for e in events if e.get("event") == "result"])

        platform.device_status = "Printing"
        await asyncio.sleep(1.0)
        assert engine.state_event()["monitors"][0]["watching"], "printing printer should be watched"
        assert not camera.standby and camera.online, "printing should wake camera capture"
        resumed = len([e for e in events if e.get("event") == "result"]) - results_during_standby
    assert resumed > 0, "inference did not resume when printing started"


async def test_zip_install_keeps_its_page_and_serves_it_on_request() -> None:
    platform = FakePlatform()
    engine = Engine(platform)
    await engine.start()
    events: list[dict] = []
    engine.add_sink(events.append)
    bundle = plugin_zip(
        manifest={**MANIFEST, "icon": "icon.png", "media": ["shots/one.png"]},
        files={"icon.png": b"\x89PNGfake", "shots/one.png": b"\x89PNGshot", "README.md": "# Demo\n\nWhat it does.".encode()},
    )
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": bundle})

    record = engine.plugins.get("demo")
    assert set(record.page) == {"icon.png", "shots/one.png", "README.md"}, "the zip's page files were not kept"
    assert "page" not in engine.state_event()["plugins"][0], "the page must not ride the every-second state snapshot"

    await engine.handle({"cmd": "plugin.page", "id": "demo", "req_id": 9})
    served = next(e for e in events if e.get("event") == "plugin_page")
    assert served["req_id"] == 9 and base64.b64decode(served["page"]["README.md"]).decode().startswith("# Demo")

    restored = Engine(platform)
    await restored.start()
    assert set(restored.plugins.get("demo").page) == set(record.page), "the page did not survive a restart"
    await restored.stop()
    await engine.stop()


async def test_unreachable_catalogue_still_answers() -> None:
    platform = FakePlatform()
    engine = Engine(platform)
    await engine.start()
    events: list[dict] = []
    engine.add_sink(events.append)
    await engine.handle({"cmd": "plugin.catalogue", "req_id": 4})
    answer = next(e for e in events if e.get("event") == "catalogue")
    assert answer["plugins"] == [] and answer["req_id"] == 4, "an unreachable catalogue must answer empty, not error"
    await engine.stop()


async def test_unreadable_printer_state_keeps_watching_and_warns(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "OFFLINE_GRACE_S", 0.2)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Detecting serial connection"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(1.0)
        assert engine.printers.get(printer_id).device_state["status"] == "unknown"
        assert engine.state_event()["monitors"][0]["watching"], "a state the adapter cannot read must keep watching"
        assert any(e.get("event") == "result" for e in events), "watching monitor did not infer"
        warnings = [e for e in events if e.get("event") == "warning" and not e["recovered"]]
        assert any("Cannot tell whether the printer" in w["message"] for w in warnings), "unreadable printer state did not warn"

        platform.device_status = "Operational"
        await asyncio.sleep(1.0)
        recoveries = [e for e in events if e.get("event") == "warning" and e["recovered"]]
        assert any("reporting its state again" in r["message"] for r in recoveries), "recovery was never announced"


async def test_restored_camera_attachment_is_single_flight(monkeypatch) -> None:
    from fakes import FakeSource
    from printguard.engine import engine as engine_module
    from printguard.engine.registry import Camera

    platform = FakePlatform()
    platform.state = {
        "cameras": [Camera(id="slow", name="Slow", source={"kind": "fake", "fps": 30.0}, max_fps=30.0).persisted()]
    }
    release = asyncio.Event()
    attempts = 0

    async def open_camera(camera_id, source):
        nonlocal attempts
        attempts += 1
        await release.wait()
        return FakeSource(30.0)

    monkeypatch.setattr(platform, "open_camera", open_camera)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.01)
    monkeypatch.setattr(engine_module, "REATTACH_EVERY_TICKS", 1)
    engine = Engine(platform)
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        assert attempts == 1
        release.set()
        await asyncio.sleep(0.02)
        assert engine.cameras.get("slow").frame_source is not None
    finally:
        await engine.stop()


async def test_removing_camera_cancels_pending_attachment(monkeypatch) -> None:
    from printguard.engine.registry import Camera

    platform = FakePlatform()
    platform.state = {
        "cameras": [Camera(id="slow", name="Slow", source={"kind": "fake", "fps": 30.0}, max_fps=30.0).persisted()]
    }
    started = asyncio.Event()

    async def open_camera(camera_id, source):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(platform, "open_camera", open_camera)
    engine = Engine(platform)
    await engine.start()
    await started.wait()

    await engine._drop_camera("slow")

    assert engine.cameras.get("slow") is None
    assert "slow" not in engine._attach_tasks
    assert platform.released_cameras == ["slow"]
    await engine.stop()


async def test_watchdog_and_failed_action(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    watchdog.DEVICE_POLL_S = 0.1
    watchdog.WATCH_TICK_S = 0.05
    watchdog.OFFLINE_GRACE_S = 0.2
    watchdog.ACT_RETRY_S = 0.01
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    monkeypatch.setattr(engine_module, "REATTACH_EVERY_TICKS", 1)
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
        failed_source = camera.frame_source
        failed_source.online = False
        await asyncio.sleep(0.6)
        warnings = [e for e in events if e.get("event") == "warning" and not e["recovered"]]
        assert any("offline" in w["message"] for w in warnings), "camera outage did not warn"
        assert any(url == "http://ntfy/topic" for _, url in platform.http_calls), "outage warning was not pushed to notifiers"
        assert camera.id in platform.released_cameras, "failed camera resources were not released"
        assert camera.frame_source is not failed_source and camera.online, "failed camera source was not attached afresh"
    recoveries = [e for e in events if e.get("event") == "warning" and e["recovered"]]
    assert any("back" in r["message"] for r in recoveries), "camera recovery was not announced"


async def test_watchdog_restarts_stalled_camera_after_fresh_inference(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", 0.1)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, events):
        camera = next(iter(engine.cameras.values()))
        await asyncio.sleep(0.1)
        stalled_source = camera.frame_source
        stalled_source.frozen = True
        await asyncio.sleep(0.5)

        assert camera.frame_source is not stalled_source and camera.online, "stalled camera source was not attached afresh"
        assert camera.id in platform.released_cameras, "stalled camera resources were not released"
        stalled_index = next(
            index
            for index, event in enumerate(events)
            if event.get("event") == "warning" and "feed has stalled" in event["message"]
        )
        recovered_index = next(
            index
            for index, event in enumerate(events)
            if event.get("event") == "warning" and event["recovered"] and "feed recovered" in event["message"]
        )
        assert any(event.get("event") == "result" for event in events[stalled_index + 1 : recovered_index])


async def test_flapping_camera_warns_once_per_outage(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "OFFLINE_GRACE_S", 0.05)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.2)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        camera = next(iter(engine.cameras.values()))

        def warnings(recovered: bool) -> list[dict]:
            return [e for e in events if e.get("event") == "warning" and e["recovered"] is recovered]

        async def hold_source(online: bool, seconds: float) -> None:
            while camera.frame_source is None:
                await asyncio.sleep(0.01)
            camera.frame_source.online = online
            await asyncio.sleep(seconds)

        for _ in range(5):
            await hold_source(False, 0.15)
            await hold_source(True, 0.1)

        assert len(warnings(False)) == 1, f"a reconnecting camera warned {len(warnings(False))} times about one episode"
        assert not warnings(True), "recovery was announced while the camera was still flapping"
        assert len(platform.http_calls) == 1, f"flapping pushed {len(platform.http_calls)} notifications"

        await hold_source(True, 0.5)
        assert len(warnings(True)) == 1, "sustained recovery was never announced"
        assert len(platform.http_calls) == 2, "recovery should push exactly once"

        await hold_source(False, 0.15)
        await hold_source(True, 0.3)
        assert len(warnings(True)) == 1, "a camera that fails again must settle for longer before recovery is announced"
        await hold_source(True, 0.6)
        assert len(warnings(True)) == 2, "recovery was never announced after the longer settled period"


async def test_protocol_surfaces_errors_and_filters_settings() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "nope", "req_id": 7})
        assert any(e["event"] == "error" and "unknown command" in e["message"] for e in events)

        await engine.handle({"cmd": "monitor.update", "id": "missing", "patch": {}, "req_id": 8})
        assert any(e["event"] == "error" and e.get("req_id") == 8 for e in events)

        assert engine.settings["theme"] == "system" and engine.settings["themes"] == [], "theme settings default"
        assert engine.settings["layout"] == {}, "layout settings default"

        custom = {"id": "t1", "name": "Mine", "base": "dark", "colors": {"accent": "#123456"}}
        layout = {
            "monitors": {"order": ["m2", "m1"], "pinned": ["m2"], "hidden": ["m3"]},
            "cameras": {"order": [], "pinned": [], "hidden": ["c1"]},
        }
        await engine.handle(
            {
                "cmd": "settings.update",
                "patch": {"bogus": 1, "notifiers": {"ntfy": {"url": "u"}}, "theme": "light", "themes": [custom], "layout": layout},
            }
        )
        assert "bogus" not in engine.settings
        assert engine.settings["notifiers"] == {"ntfy": {"url": "u"}}
        assert engine.settings["theme"] == "light"
        assert engine.settings["themes"] == [custom]
        assert engine.settings["layout"] == layout

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.settings["layout"] == layout, "layout settings survive a restart"


async def test_provider_change_clears_stale_printer_state(monkeypatch) -> None:
    platform = FakePlatform()
    closed: list[dict | None] = []

    async def close(config=None):
        closed.append(config)

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "close", close)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        engine.printers.get(printer_id).device_state = {"status": "printing", "progress": 1.0, "job": None}
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "Renamed"}})
        assert engine.printers.get(printer_id).device_state["status"] == "printing", "same provider must keep its state"
        assert closed == []

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://kl"}}})
        assert engine.printers.get(printer_id).device_state is None, "a new provider must not inherit the old state"
        assert closed == [OCTOPRINT["config"]]
    assert closed == [OCTOPRINT["config"], None]


async def test_printer_camera_registers_cascades_and_is_managed(monkeypatch) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        async def fake_cameras(http, config):
            return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0}}]

        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", fake_cameras)
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)  # printer.add reconciles its cameras in the background

        cameras = engine.cameras.values()
        assert [c.name for c in cameras] == ["Shop cam"], "the printer's camera was registered on add"
        camera = cameras[0]
        assert camera.id == f"{printer_id}-webcam" and camera.printer_id == printer_id

        await engine.reconcile_printer_cameras(engine.printers.get(printer_id))
        assert len(engine.cameras.values()) == 1, "reconciling again must not duplicate the camera"

        await engine.handle({"cmd": "camera.remove", "id": camera.id, "req_id": 99})
        assert engine.cameras.get(camera.id) is not None, "a managed camera cannot be removed on its own"
        assert any(e["event"] == "error" and e.get("req_id") == 99 for e in events)

        await engine.handle({"cmd": "printer.remove", "id": printer_id})
        assert engine.cameras.get(camera.id) is None, "removing the printer drops its camera"


async def test_camera_add_delegates_whep_url_to_platform() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.add", "name": "Cam", "source": {"kind": "url", "url": "whep://pi:8889/cam/whep"}, "req_id": 5})
        assert [camera.name for camera in engine.cameras.values()] == ["Cam"]
        assert not any(event["event"] == "error" and event.get("req_id") == 5 for event in events)


async def test_printer_whep_camera_registers_via_platform(monkeypatch) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        async def webrtc_cameras(http, config):
            return [{"key": "webcam", "name": "Chamber", "source": {"kind": "url", "url": "whep://pi:8889/chamber/whep"}}]

        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webrtc_cameras)
        await _register_printer(engine)
        await asyncio.sleep(0.1)  # printer.add reconciles its cameras in the background
        assert [camera.name for camera in engine.cameras.values()] == ["Chamber"]


async def test_orphaned_managed_camera_can_be_removed() -> None:
    from printguard.engine.registry import Camera

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        engine.cameras.add(Camera(id="ghost", name="Ghost", source={"kind": "fake", "fps": 5.0}, printer_id="gone", max_fps=5.0))
        await engine.handle({"cmd": "camera.remove", "id": "ghost"})
        assert engine.cameras.get("ghost") is None, "a managed camera whose printer no longer exists is removable"


async def test_camera_attached_later_is_picked_up_on_refresh(monkeypatch) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        exposed: list[dict] = []

        async def fake_cameras(http, config):
            return list(exposed)

        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", fake_cameras)
        await _register_printer(engine)
        await asyncio.sleep(0.1)
        assert not engine.cameras.values(), "no camera while the service exposes none"

        exposed.append({"key": "webcam", "name": "Late cam", "source": {"kind": "fake", "fps": 15.0}})
        await engine.handle({"cmd": "printer.cameras.refresh"})
        assert [c.name for c in engine.cameras.values()] == ["Late cam"], "refresh picks up a camera added later"


async def test_state_persists_across_restart() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": "Resurrected", "notify": True, "printer_id": printer_id}})
        await engine.handle({"cmd": "settings.update", "patch": {"theme": "light", "inference_runtime": "onnx"}})
        assert platform.inference_runtime == "onnx"

    reborn = Engine(platform)
    await reborn.start()
    try:
        assert reborn.settings["theme"] == "light", "theme survives a restart"
        assert reborn.settings["inference_runtime"] == "onnx"
        assert platform.inference_runtime == "onnx"
        assert [c.name for c in reborn.cameras.values()] == ["cam10.0"]
        restored = reborn.monitors[monitor_id]
        assert restored["name"] == "Resurrected"
        assert restored["notify"] is True
        assert restored["printer_id"] == printer_id
        printer = reborn.printers.get(printer_id)
        assert printer and printer.name == "P" and printer.provider == "octoprint"
    finally:
        await reborn.stop()


def test_rotate_frame_and_transform_compose() -> None:
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[0, 0] = (255, 0, 0)

    assert vision.rotate_frame(frame, 0).shape == (48, 64, 3)
    assert vision.rotate_frame(frame, 180).shape == (48, 64, 3)
    assert vision.rotate_frame(frame, 90).shape == (64, 48, 3)
    assert vision.rotate_frame(frame, 270).shape == (64, 48, 3)

    rotated = vision.rotate_frame(frame, 90)
    assert tuple(rotated[0, -1]) == (255, 0, 0), "90 deg clockwise sends top-left to top-right"

    cropped = vision.transform(frame, rotation=90, crop={"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0})
    assert cropped.shape == (64, 24, 3), "crop is applied on the rotated frame"


async def test_camera_rotation_persists_and_rejects_off_axis() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"rotation": 90}})
        assert camera.rotation == 90
        assert camera.public()["rotation"] == 90
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"rotation": 45}})
        assert camera.rotation == 0, "off-axis rotation falls back to 0"
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"rotation": 270}})

    reborn = Engine(platform)
    await reborn.start()
    try:
        assert reborn.cameras.values()[0].rotation == 270, "rotation survives a restart"
    finally:
        await reborn.stop()


async def test_history_buckets_and_alert_snapshots() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(1.5)
        history = next(e for e in await engine.request({"cmd": "history.get", "monitor_id": monitor_id}) if e["event"] == "history")
        snaps = history["snaps"]
        assert snaps, "a fired alert should capture a snapshot"
        snapshot = next(e for e in await engine.request({"cmd": "snapshot.get", "monitor_id": monitor_id, "id": snaps[0]["id"]}) if e["event"] == "snapshot")
        state_result = engine.state_event()["monitors"][0]["result"]

    buckets, stats = history["buckets"], history["stats"]
    assert buckets and buckets[0]["n"] > 0, "no inference was folded into a bucket"
    assert state_result and state_result["ts"] >= buckets[-1]["t"], "state snapshot should carry the latest live score"
    assert history["now"] >= buckets[-1]["t"], "history windows should use the engine clock"
    assert stats["inferences"] == sum(b["n"] for b in buckets)
    assert stats["defect_frames"] > 0 and stats["defect_pct"] > 0, "sustained defect not counted"
    assert stats["alerts"] == 1 and len(snaps) == 1, "the cooldown holds a sustained defect to one alert and one snapshot"
    assert snaps[0]["action"] == "none" and snaps[0]["score"] >= 0.6, "snapshot carries the alert's action and score"
    assert base64.b64decode(snapshot["jpeg"]) == b"\xff\xd8fake", "snapshot bytes did not round-trip over the protocol"


async def test_result_events_are_bounded_without_losing_history() -> None:
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(1.2)
        history = next(e for e in await engine.request({"cmd": "history.get", "monitor_id": monitor_id}) if e["event"] == "history")

    results = [event for event in events if event.get("event") == "result"]
    assert 3 <= len(results) <= 7
    assert history["stats"]["inferences"] > len(results) * 2


async def test_camera_restart_cancels_stuck_inference() -> None:
    platform = FakePlatform(infer_s=0.01)
    platform.inference_blocked = True
    async with running_engine(platform, camera_fps=[30.0]) as (engine, events):
        await asyncio.wait_for(platform.inference_started.wait(), timeout=1.0)
        camera = next(iter(engine.cameras.values()))
        await engine.restart_camera(camera)
        platform.inference_blocked = False
        await asyncio.sleep(0.2)

    assert any(event.get("event") == "result" for event in events)


async def test_no_alert_means_no_snapshot() -> None:
    platform = FakePlatform(infer_s=0.02, failing=False)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(1.0)
        history = next(e for e in await engine.request({"cmd": "history.get", "monitor_id": monitor_id}) if e["event"] == "history")
    assert history["buckets"], "buckets should fill even without defects"
    assert history["stats"]["defect_frames"] == 0
    assert history["snaps"] == [] and history["stats"]["alerts"] == 0, "no alert means no snapshot"


async def test_monitor_remove_clears_history() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(0.5)
        assert engine.history[monitor_id].buckets, "history should accumulate while watching"
        await engine.handle({"cmd": "monitor.remove", "id": monitor_id})
        assert monitor_id not in engine.history, "history is dropped with its monitor"


@asynccontextmanager
async def configured_logging():
    """Installs the real logging setup for a test, restoring pytest's after."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    logs.tail.lines.clear()
    logs.setup()
    try:
        yield
    finally:
        root.handlers.clear()
        for handler in handlers:
            root.addHandler(handler)
        root.setLevel(level)


async def test_report_send_redacts_credentials_and_posts_feedback() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with configured_logging(), running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle(
            {"cmd": "camera.add", "name": "ip cam", "source": {"kind": "url", "url": "rtsp://user:hunter2@cam.local/stream", "fps": 5.0}}
        )
        await engine.handle(
            {"cmd": "printer.add", "printer": {"name": "P", "provider": "octoprint", "config": {"base_url": "http://op", "api_key": "octo-secret"}}}
        )
        await engine.handle(
            {
                "cmd": "settings.update",
                "patch": {
                    "notifiers": {"telegram": {"bot_token": "tg-secret", "chat_id": "1"}},
                    "mqtt": {"host": "broker", "password": "mqtt-secret"},
                },
            }
        )
        logging.getLogger("printguard.test").warning("upstream rejected credential octo-secret")
        await engine.handle(
            {
                "cmd": "report.send",
                "req_id": 9,
                "message": "the feed froze",
                "email": "user@example.com",
                "client": {"url": "http://hub/#hub", "user_agent": "TestBrowser"},
                "logs": ["2026-07-04T10:00:00Z ERROR notifier tg-secret rejected"],
                "attachments": [{"name": "shot.png", "type": "image/png", "data": base64.b64encode(b"\x89PNG fake").decode()}],
            }
        )

    sent = [e for e in events if e.get("event") == "report_sent"]
    assert sent and sent[0]["ok"] and sent[0]["req_id"] == 9
    endpoint = reports.envelope_endpoint(reports.SENTRY_DSN)
    request = next(r for r in platform.http_requests if r["url"] == endpoint)
    assert request["headers"]["Content-Type"] == "application/x-sentry-envelope"
    lines = request["data"].split(b"\n")
    assert json.loads(lines[1]) == {"type": "feedback"}
    event = json.loads(lines[2])
    assert event["contexts"]["feedback"] == {"message": "the feed froze", "contact_email": "user@example.com", "url": "http://hub/#hub"}
    assert event["release"] == f"printguard@{platform.version}" and event["environment"] == "docker"
    text = request["data"].decode(errors="replace")
    for secret in ("hunter2", "octo-secret", "tg-secret", "mqtt-secret"):
        assert secret not in text, f"credential {secret!r} leaked into the report"
    assert "rtsp://cam.local/stream" in text, "camera URL should keep its shape without credentials"
    assert "diagnostics.json" in text and "shot.png" in text
    for log_file, marker in (("engine.log", "upstream rejected credential [redacted]"), ("ui.log", "notifier [redacted] rejected")):
        assert f'"filename": "{log_file}"' in text and marker in text, f"{log_file} missing or not scrubbed"
    assert "engine started" in text, "engine lifecycle lines missing from the attached log tail"
    assert b"\x89PNG fake" in request["data"], "user attachment bytes missing from the envelope"


async def test_report_bundle_downloads_the_same_scrubbed_files() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with configured_logging(), running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle(
            {"cmd": "printer.add", "printer": {"name": "P", "provider": "octoprint", "config": {"base_url": "http://op", "api_key": "octo-secret"}}}
        )
        logging.getLogger("printguard.test").warning("upstream rejected credential octo-secret")
        await engine.handle({"cmd": "report.bundle", "req_id": 4, "logs": ["ui line with octo-secret"]})

    bundle = next(e for e in events if e.get("event") == "report_bundle")
    assert bundle["req_id"] == 4 and bundle["filename"].startswith("printguard-diagnostics-")
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle["zip"]))) as archive:
        assert archive.namelist() == ["diagnostics.json", "engine.log", "ui.log"]
        contents = {name: archive.read(name).decode() for name in archive.namelist()}
    assert json.loads(contents["diagnostics.json"])["printers"][0]["config"]["api_key"] == reports.REDACTED
    for name, text in contents.items():
        assert "octo-secret" not in text, f"credential leaked into {name}"
    assert not any(r["url"].startswith("https://") for r in platform.http_requests), "a download must send nothing"


async def test_report_send_surfaces_failure() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "report.send", "req_id": 1, "message": "   "})
        platform.report_status = 429
        await engine.handle({"cmd": "report.send", "req_id": 2, "message": "still broken"})

    sent = [e for e in events if e.get("event") == "report_sent"]
    assert [e["ok"] for e in sent] == [False, False]
    assert "description" in sent[0]["error"]
    assert "429" in sent[1]["error"]


async def test_token_secret_reaches_requester_but_is_never_logged(monkeypatch) -> None:
    monkeypatch.setitem(EVENT_LOG_LEVELS, "token_created", logging.ERROR)
    platform = FakePlatform(infer_s=0.02)
    async with configured_logging(), running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "token.create", "req_id": 7, "name": "ci", "scope": "control"})

    created = next(e for e in events if e.get("event") == "token_created")
    assert created["req_id"] == 7 and created["scope"] == "control"
    assert engine.tokens.get(created["id"]) is not None, "token was not registered"
    secret = created["token"]
    assert secret.startswith("pg_"), "requester did not receive the one-time secret"
    assert all(secret not in line for line in logs.recent()), "token secret leaked into the log tail"


MANIFEST = {
    "id": "demo",
    "name": "Demo",
    "version": "1.0.0",
    "permissions": ["state:read", "monitor:control", "net"],
    "reasons": {"state:read": "to read", "monitor:control": "to retune", "net": "to post"},
    "urls": ["https://hooks.example.com/*", "wss://hooks.example.com/*"],
}
PLUGIN_JS = "plugin.render = (state) => ({ type: 'text', value: state.monitors.length + ' monitors' });"


def plugin_zip(
    manifest: dict | None = None, code: str = PLUGIN_JS, files: dict[str, bytes] | None = None, panel: str | None = None
) -> str:
    """Packs a plugin bundle the way an imported file arrives."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest if manifest is not None else MANIFEST))
        archive.writestr("plugin.js", code)
        if panel is not None:
            archive.writestr("panel.html", panel)
        for name, data in (files or {}).items():
            archive.writestr(name, data)
    return base64.b64encode(buffer.getvalue()).decode()


async def install_demo(engine: Engine, granted: list[str] | None = None, **extra) -> dict:
    """Installs the demo plugin from a file, accepting its permissions as the user would."""
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(), **extra})
    accepted = MANIFEST["permissions"] if granted is None else granted
    await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": accepted, "enabled": True}})
    return engine.plugins.get("demo").public()


async def test_plugin_installs_from_a_file_without_its_code_in_the_snapshot() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        record = await install_demo(engine, granted=["state:read", "printer:control"])

    assert record["verified"] is False, "nothing in the catalogue vouched for this bundle"
    assert record["granted"] == ["state:read"], "a permission the manifest never asked for was granted"
    assert record["digests"]["plugin.js"] == hashlib.sha256(PLUGIN_JS.encode()).hexdigest()
    snapshot = json.dumps(next(e for e in events if e.get("event") == "state" and e.get("plugins")))
    assert PLUGIN_JS not in snapshot, "plugin source rode along in the state snapshot"


async def test_a_manifest_stored_by_an_older_version_comes_back_in_todays_shape() -> None:
    """A record written before a manifest field existed still restores complete.

    Both sandboxes and the dashboard read the sanitised manifest, so a stored
    one missing whatever has been added since would arrive short.
    """
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine)
    stored = platform.state["plugins"][0]
    stored["manifest"] = {k: v for k, v in stored["manifest"].items() if k not in ("consumes", "provides", "oauth")}

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        restored = engine.plugins.get("demo")

    assert restored is not None, "a plugin was dropped over a manifest an older version wrote"
    assert restored.manifest["consumes"] == [] and restored.manifest["oauth"] == {}
    assert restored.granted == MANIFEST["permissions"], "restoring the record threw the grants away"


async def test_a_stored_manifest_that_no_longer_validates_is_dropped() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine)
    platform.state["plugins"][0]["manifest"]["reasons"] = {}

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.plugins.get("demo") is None, "a manifest this version cannot read was restored anyway"


async def test_plugin_code_reaches_only_the_tab_that_asked() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle({"cmd": "plugin.code", "id": "demo", "req_id": 12})

    code = next(e for e in events if e.get("event") == "plugin_code")
    assert code["req_id"] == 12 and code["sources"]["plugin.js"] == PLUGIN_JS


async def test_plugin_installs_from_github_pinned_to_a_commit() -> None:
    platform = FakePlatform(infer_s=0.02)
    sha = "a" * 40
    platform.files = {
        "https://api.github.com/repos/someone/pack/commits/main": (200, {"sha": sha}),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/plugin.json": (200, MANIFEST),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/plugin.js": (200, PLUGIN_JS),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/worker.js": (404, ""),
    }
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "github", "repo": "someone/pack", "path": "kit", "ref": "main"}}
        )
        record = engine.plugins.get("demo")

    assert record.source["ref"] == sha, "a moving branch was stored instead of the commit it resolved to"
    assert list(record.sources) == ["plugin.js"]


def github_files(sha: str, manifest: dict, repo: str = "someone/pack") -> dict:
    """The GitHub endpoints an install of one plugin reads."""
    return {
        f"https://api.github.com/repos/{repo}/commits/main": (200, {"sha": sha}),
        f"https://raw.githubusercontent.com/{repo}/{sha}/plugin.json": (200, manifest),
        f"https://raw.githubusercontent.com/{repo}/{sha}/plugin.js": (200, PLUGIN_JS),
        f"https://raw.githubusercontent.com/{repo}/{sha}/worker.js": (404, ""),
        f"https://raw.githubusercontent.com/{repo}/{sha}/panel.html": (404, ""),
    }


async def install_from_github(engine: Engine, repo: str = "someone/pack") -> None:
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "github", "repo": repo, "ref": "main"}})


async def test_an_update_from_the_same_repository_keeps_what_the_user_gave_it() -> None:
    """The repository is the plugin's signature, so its own update carries on."""
    platform = FakePlatform(infer_s=0.02)
    platform.files = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        platform.files = github_files("b" * 40, {**SECRET_MANIFEST, "version": "1.1.0"})
        await install_from_github(engine)
        updated = engine.plugins.get("vault")

    assert updated.manifest["version"] == "1.1.0", "the new revision did not replace the old one"
    assert updated.secrets["api_key"] == "s3cr3t", "an update made the user type its credentials again"
    assert updated.enabled and updated.granted == SECRET_MANIFEST["permissions"]


async def test_an_update_that_reaches_further_stands_the_plugin_down() -> None:
    """A wider manifest is a fresh question, the way a browser asks one again."""
    platform = FakePlatform(infer_s=0.02)
    platform.files = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        wider = {**SECRET_MANIFEST, "urls": [*SECRET_MANIFEST["urls"], "https://collector.example.com/*"]}
        platform.files = github_files("b" * 40, wider)
        await install_from_github(engine)
        updated = engine.plugins.get("vault")

    assert updated.granted == [], "an address nobody accepted was reached under the old consent"
    assert not updated.enabled, "a plugin that widened its reach kept running"
    assert updated.secrets["api_key"] == "s3cr3t", "the same plugin's own credentials were thrown away"


async def test_a_bundle_from_somewhere_else_inherits_nothing_but_the_id() -> None:
    """An id is not an identity, so a stranger holding one starts with nothing."""
    platform = FakePlatform(infer_s=0.02)
    platform.files = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        platform.files = github_files("c" * 40, SECRET_MANIFEST, repo="squatter/pack")
        await install_from_github(engine, repo="squatter/pack")
        squatted = engine.plugins.get("vault")

    assert squatted.secrets == {}, "another author's bundle inherited the credentials"
    assert squatted.granted == [] and not squatted.enabled, "it ran on consent given to somebody else"


async def test_catalogue_verifies_only_the_exact_bytes_it_pinned() -> None:
    platform = FakePlatform(infer_s=0.02)
    digests = plugins.digests(plugins.sanitise_manifest(MANIFEST), {"plugin.js": PLUGIN_JS}, {})
    platform.files = {plugins.CATALOGUE_URL: (200, {"plugins": [{"id": "demo", "name": "Demo", "digests": digests}]})}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert (await install_demo(engine))["verified"] is True
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(code=PLUGIN_JS + "//")})
        tampered = engine.plugins.get("demo").public()

    assert tampered["verified"] is False, "an edited plugin still passed as verified"


async def test_plugin_network_is_refused_beyond_the_patterns_it_declared() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/a", "req_id": 1})
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://elsewhere.example/a", "req_id": 2})
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "http://hooks.example.com/a", "req_id": 4})
        await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": []}})
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/a", "req_id": 3})

    assert next(e for e in events if e.get("event") == "http")["req_id"] == 1
    refused = [e for e in events if e.get("event") == "error" and e.get("req_id") in (2, 3, 4)]
    assert len(refused) == 3, "an undeclared pattern, scheme or a revoked permission still got out"
    assert not any("elsewhere.example" in url for _, url in platform.http_calls)


async def test_a_request_naming_a_secret_it_has_not_got_never_leaves() -> None:
    platform = FakePlatform(infer_s=0.02)
    wanting = {**MANIFEST, "secrets": {"api_key": "The key from your account page"}}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest=wanting)})
        await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": MANIFEST["permissions"], "enabled": True}})
        signed = {"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/a", "headers": {"Authorization": "Bearer {{secret.api_key}}"}}
        await engine.handle({**signed, "req_id": 1})
        await engine.handle({"cmd": "plugin.secrets", "id": "demo", "secrets": {"api_key": "k3y"}})
        await engine.handle({**signed, "req_id": 2})

    refused = [e for e in events if e.get("event") == "error" and e.get("req_id") == 1]
    assert len(refused) == 1, "a half-filled header went out instead of being refused"
    assert "api_key" in refused[0]["message"], refused[0]["message"]
    assert [e.get("req_id") for e in events if e.get("event") == "http"] == [2]


async def test_a_plugin_reaching_this_network_needs_the_grant_that_covers_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {
        **MANIFEST,
        "permissions": ["net"],
        "reasons": {"net": "to poke the printer"},
        "urls": ["http://192.168.1.50/*"],
    }
    with pytest.raises(ValueError, match="net:local"):
        plugins.sanitise_manifest(manifest)

    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/a", "req_id": 5})

    assert any(e.get("event") == "http" and e.get("req_id") == 5 for e in events)


async def test_a_plugin_stays_off_until_every_permission_it_asks_for_is_accepted() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip()})
        fresh = (engine.plugins.get("demo").enabled, engine.plugins.get("demo").granted)
        await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["net"], "enabled": True}})
        partial = engine.plugins.get("demo").enabled
        await engine.handle(
            {"cmd": "plugin.update", "id": "demo", "patch": {"granted": MANIFEST["permissions"], "enabled": True}}
        )
        accepted = (engine.plugins.get("demo").enabled, engine.plugins.get("demo").granted)

    assert fresh == (False, []), "a plugin ran before anyone accepted anything"
    assert not partial, "accepting some of the permissions was enough to enable it"
    assert accepted == (True, MANIFEST["permissions"])


async def test_a_plugin_asking_for_more_stands_down_until_the_wider_list_is_accepted() -> None:
    platform = FakePlatform(infer_s=0.02)
    wider = {
        **MANIFEST,
        "permissions": [*MANIFEST["permissions"], "printer:control"],
        "reasons": {**MANIFEST["reasons"], "printer:control": "to pause"},
    }
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine)
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(wider)})
        widened = engine.plugins.get("demo")
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip()})
        narrowed = engine.plugins.get("demo")

    assert not widened.enabled, "an update that asked for more kept running"
    assert not widened.may("printer:control")
    assert not narrowed.enabled, "reinstalling re-enabled a plugin the user had not re-accepted"


async def test_a_manifest_without_a_reason_for_a_permission_is_refused() -> None:
    with pytest.raises(ValueError, match="reasons"):
        plugins.sanitise_manifest({**MANIFEST, "reasons": {"state:read": "to read"}})


async def test_a_plugins_request_comes_back_tagged_as_it_named_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.files["https://hooks.example.com/feed"] = (200, {"temp": 4})
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle(
            {"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/feed", "tag": "forecast"}
        )

    answer = next(e for e in events if e.get("event") == "http")
    assert answer["tag"] == "forecast" and answer["status"] == 200 and answer["body"] == {"temp": 4}
    assert answer["id"] == "demo", "an answer that did not say whose request it was"


async def test_a_plugin_making_requests_too_fast_is_refused() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        for index in range(engine_module.PLUGIN_RATE_LIMIT + 5):
            await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/a", "req_id": index})

    assert len([e for e in events if e.get("event") == "http"]) == engine_module.PLUGIN_RATE_LIMIT
    assert any("faster than" in str(e.get("message")) for e in events if e.get("event") == "error")


async def test_a_plugin_holds_a_socket_and_hears_what_arrives_on_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle(
            {"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://hooks.example.com/live"}
        )
        socket = platform.sockets[-1]
        socket.arrived("message", '{"hello": true}')
        await engine.handle({"cmd": "plugin.socket", "id": "demo", "action": "send", "tag": "feed", "text": "ping"})
        await engine.handle({"cmd": "plugin.socket", "id": "demo", "action": "close", "tag": "feed"})

    frames = [e for e in events if e.get("event") == "socket"]
    assert [f["state"] for f in frames] == ["open", "message", "closed"]
    assert frames[1]["text"] == '{"hello": true}' and all(f["tag"] == "feed" for f in frames)
    assert socket.sent == ["ping"] and socket.closed


async def test_a_disabled_plugin_loses_the_sockets_it_was_holding() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine)
        await engine.handle(
            {"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://hooks.example.com/live"}
        )
        await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"enabled": False}})

    assert platform.sockets[-1].closed, "a socket outlived the plugin holding it"


SOUND_MANIFEST = {
    "id": "chimes",
    "name": "Chimes",
    "version": "1.0.0",
    "permissions": ["sound"],
    "reasons": {"sound": "to sound an alert"},
}


async def install_chimes(engine: Engine, granted: list[str]) -> None:
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(SOUND_MANIFEST)})
    await engine.handle({"cmd": "plugin.update", "id": "chimes", "patch": {"granted": granted, "enabled": bool(granted)}})


async def test_an_effect_only_a_dashboard_can_perform_is_passed_on_to_them() -> None:
    """A worker has no speakers, so it asks and whoever has a dashboard open does it."""
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_chimes(engine, granted=["sound"])
        await engine.handle({"cmd": "plugin.effect", "id": "chimes", "effect": {"kind": "sound", "asset": "horn.mp3"}})
        passed = [e for e in events if e.get("event") == "plugin_effect"]

    assert passed == [
        {"event": "plugin_effect", "id": "chimes", "effect": {"kind": "sound", "asset": "horn.mp3"}, "req_id": None}
    ]


async def test_an_effect_the_plugin_was_not_granted_reaches_no_dashboard() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_chimes(engine, granted=[])
        await engine.handle(
            {"cmd": "plugin.effect", "id": "chimes", "effect": {"kind": "sound", "asset": "horn.mp3"}, "req_id": 1}
        )
        await install_chimes(engine, granted=["sound"])
        await engine.handle(
            {"cmd": "plugin.effect", "id": "chimes", "effect": {"kind": "command", "cmd": {"cmd": "monitor.remove"}}, "req_id": 2}
        )
        refused = [e for e in events if e.get("event") == "error" and e.get("req_id") in (1, 2)]
        passed = [e for e in events if e.get("event") == "plugin_effect"]

    assert len(refused) == 2, "an ungranted sound, or a command dressed as one, went to the dashboards"
    assert passed == [], "an effect nobody granted was handed on"


SECRET_MANIFEST = {
    "id": "vault",
    "name": "Vault",
    "version": "1.0.0",
    "permissions": ["net", "oauth"],
    "reasons": {"net": "to post", "oauth": "to sign in"},
    "urls": ["https://api.example.com/*"],
    "secrets": {"api_key": "The key from your account page"},
    "oauth": {
        "authorize_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "scopes": ["read"],
    },
}


async def install_vault(engine: Engine) -> None:
    """Installs the secret-holding demo plugin, accepted and given a client id."""
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(SECRET_MANIFEST)})
    await engine.handle(
        {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
    )
    await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"oauth_client_id": "registered-app"}})


async def test_a_secret_is_filled_in_on_the_way_out_and_read_back_by_nobody() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        await engine.handle({
            "cmd": "plugin.http", "id": "vault", "method": "POST", "url": "https://api.example.com/v1/ping",
            "headers": {"Authorization": "Bearer {{secret.api_key}}"}, "json": {"key": "{{secret.api_key}}"},
        })
        record = engine.plugins.get("vault").public()

    sent = platform.http_requests[-1]
    assert sent["headers"]["Authorization"] == "Bearer s3cr3t", "the secret never reached the request"
    assert sent["json"] == {"key": "s3cr3t"}
    assert record["secrets_set"] == ["api_key", "oauth_client_id"] and "secrets" not in record, "a secret rode along in the state snapshot"
    assert "s3cr3t" not in json.dumps([e for e in events if e.get("event") == "state"])


async def test_a_secret_the_manifest_never_declared_is_not_stored() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "kept", "sneaky": "dropped"}})
        held = engine.plugins.get("vault").secrets

    assert held == {"api_key": "kept", "oauth_client_id": "registered-app"}


async def test_a_sign_in_ends_with_tokens_the_plugin_can_use_but_never_see() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.files["https://auth.example.com/token"] = (
        200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
    )
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "start", "origin": "http://127.0.0.1:8000"})
        opened = next(e for e in events if e.get("event") == "plugin_oauth")["url"]
        state = parse_qs(urlparse(opened).query)["state"][0]
        name = await engine.finish_sign_in(state, "code-1")

        await engine.handle({
            "cmd": "plugin.http", "id": "vault", "url": "https://api.example.com/v1/me",
            "headers": {"Authorization": "Bearer {{secret.oauth}}"},
        })
        record = engine.plugins.get("vault").public()

    query = parse_qs(urlparse(opened).query)
    assert query["code_challenge_method"] == ["S256"] and "code_challenge" in query, "the sign-in skipped PKCE"
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/oauth/callback"]
    assert name == "Vault"
    assert platform.http_requests[-1]["headers"]["Authorization"] == "Bearer at-1"
    assert "oauth" in record["secrets_set"] and "at-1" not in json.dumps(record)


async def test_a_client_id_comes_from_whoever_installed_it_and_never_the_bundle() -> None:
    """A plugin travels as a repo, a zip or a listing, so a client id in it would
    be one app shared by everybody who installed it."""
    platform = FakePlatform(infer_s=0.02)
    shipped = {**SECRET_MANIFEST, "oauth": {**SECRET_MANIFEST["oauth"], "client_id": "the-authors-app"}}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(shipped)})
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": shipped["permissions"], "enabled": True}}
        )
        manifest = engine.plugins.get("vault").manifest
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "start", "origin": "http://127.0.0.1:8000", "req_id": 7})
        refused = [e for e in events if e.get("event") == "error" and e.get("req_id") == 7]

        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"oauth_client_id": "mine-1234"}})
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "start", "origin": "http://127.0.0.1:8000"})
        opened = next(e for e in events if e.get("event") == "plugin_oauth")["url"]

    assert "client_id" not in manifest["oauth"], "a client id in the bundle survived the install"
    assert oauth.CLIENT_ID in manifest["secrets"], "nobody was asked for a client id"
    assert len(refused) == 1, "a sign-in started before anyone supplied one"
    assert parse_qs(urlparse(opened).query)["client_id"] == ["mine-1234"]


async def test_disconnecting_keeps_the_client_id_the_user_registered() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        plugin = engine.plugins.get("vault")
        plugin.secrets = {"oauth_client_id": "mine-1234", "oauth": "at-1", "oauth_refresh": "rt-1"}
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "forget"})

    assert plugin.secrets == {"oauth_client_id": "mine-1234"}, "signing out threw away the registered app"


async def test_a_callback_nobody_asked_for_is_refused() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        assert await engine.finish_sign_in("made-up", "code-1") is None


async def test_an_expiring_access_token_is_renewed_before_the_request_goes_out() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.files["https://auth.example.com/token"] = (
        200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600},
    )
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        plugin = engine.plugins.get("vault")
        plugin.secrets = {**plugin.secrets, "oauth": "stale", "oauth_refresh": "rt-1", "oauth_expires": "0"}
        await engine.handle({
            "cmd": "plugin.http", "id": "vault", "url": "https://api.example.com/v1/me",
            "headers": {"Authorization": "Bearer {{secret.oauth}}"},
        })

    assert platform.http_requests[-1]["headers"]["Authorization"] == "Bearer at-2", "a stale token went out"
    assert plugin.secrets["oauth_refresh"] == "rt-2", "a rotated refresh token was thrown away"


async def test_a_plugin_reaches_the_whole_command_table_it_was_granted() -> None:
    """Every command a permission names dispatches, so the table cannot rot."""
    unreachable = [command for command in plugins.PERMISSION_COMMANDS if command not in Engine(FakePlatform())._handlers]

    assert unreachable == []


async def test_a_plugin_can_take_a_still_of_a_camera_as_it_looks_now() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        camera_id = next(iter(engine.cameras.items))
        await engine.handle({"cmd": "camera.snapshot", "camera_id": camera_id, "req_id": 9})

    frame = next(e for e in events if e.get("event") == "frame")
    assert frame["camera_id"] == camera_id and frame["req_id"] == 9
    assert base64.b64decode(frame["jpeg"]), "the still came back empty"
    assert "camera.snapshot" in plugins.PERMISSION_COMMANDS, "taking a still needs a permission"
    assert plugins.PERMISSIONS[plugins.PERMISSION_COMMANDS["camera.snapshot"]]["risky"] is True


async def test_a_camera_with_no_frame_yet_says_so_rather_than_handing_back_nothing() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.snapshot", "camera_id": "nope", "req_id": 10})

    assert any(e.get("event") == "error" and e.get("req_id") == 10 for e in events)
    assert not any(e.get("event") == "frame" for e in events)


async def test_risk_history_reaches_a_plugin_without_a_store_of_its_own() -> None:
    """The rollups the detail page already draws, projected by the same table."""
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(0.4)
        await engine.handle({"cmd": "history.get", "monitor_id": monitor_id})

    raw = next(e for e in events if e.get("event") == "history")
    seen = plugins.project_event(raw, ["history:read"])

    assert seen is not None and seen["monitor_id"] == monitor_id
    assert set(seen) == {"event", "monitor_id", "now", "buckets", "alerts", "stats"}
    assert "snaps" not in seen, "the snapshot index rode along to a plugin"


async def test_an_event_carrying_something_a_permission_covers_reaches_nobody_else() -> None:
    """A plugin naming an event cannot wait for another to ask and read the answer."""
    still = {"event": "frame", "camera_id": "c1", "jpeg": "abc"}
    history = {"event": "history", "monitor_id": "m1", "now": 1.0, "buckets": [], "alerts": [], "stats": {}}

    assert plugins.project_event(still, ["camera:frames"]) is not None
    assert plugins.project_event(still, ["state:read"]) is None
    assert plugins.project_event(history, ["history:read"]) is not None
    assert plugins.project_event(history, []) is None
    assert plugins.project_event({"event": "alert", "monitor_id": "m1"}, []) is not None


async def test_a_plugin_draws_its_own_panel_and_ships_the_media_for_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "id": "painter", "assets": ["loop.mp4"], "surfaces": ["panel"]}
    files = {"loop.mp4": b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64}
    panel = "<style>body{margin:0}</style><video autoplay muted loop></video><script>pg.log('up')</script>"
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest, files=files, panel=panel)}
        )
        plugin = engine.plugins.get("painter")

    assert plugin.sources["panel.html"] == panel
    assert plugin.digests["panel.html"] == hashlib.sha256(panel.encode()).hexdigest()
    assert plugin.digests["loop.mp4"] == hashlib.sha256(files["loop.mp4"]).hexdigest()
    assert "loop.mp4" not in plugins.text_assets(plugin.assets), "a video reached the sandbox as text"


async def test_a_file_claiming_to_be_video_but_is_not_never_installs() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "assets": ["loop.mp4"]}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest, files={"loop.mp4": b"<script>"})}
        )

    assert engine.plugins.get("demo") is None
    assert any("not really video/mp4" in str(e.get("message")) for e in events if e.get("event") == "error")


PROVIDER = {
    "id": "spotify", "name": "Spotify", "version": "1.0.0",
    "permissions": ["link:provide"], "reasons": {"link:provide": "to share the track"},
    "provides": {"now-playing": "The track playing right now"},
}
CONSUMER = {
    "id": "np-widget", "name": "Now playing", "version": "1.0.0",
    "permissions": ["link:consume"], "reasons": {"link:consume": "to draw the track"},
    "consumes": ["spotify:now-playing"],
}


async def install_pair(engine: Engine) -> None:
    """Installs a provider and a consumer, both accepted."""
    for manifest in (PROVIDER, CONSUMER):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest)})
        await engine.handle(
            {"cmd": "plugin.update", "id": manifest["id"], "patch": {"granted": manifest["permissions"], "enabled": True}}
        )


async def test_one_plugin_asks_another_and_the_answer_comes_back_to_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_pair(engine)
        await engine.handle(
            {"cmd": "plugin.call", "id": "np-widget", "to": "spotify", "channel": "now-playing", "tag": "np", "body": {"q": 1}}
        )
        asked = next(e for e in events if e.get("event") == "call")
        await engine.handle(
            {"cmd": "plugin.answer", "id": "spotify", "call_id": asked["call_id"], "channel": "now-playing", "body": {"track": "Blue"}}
        )
        answer = next(e for e in events if e.get("event") == "answer")

    assert asked["id"] == "spotify" and asked["from"] == "np-widget" and asked["body"] == {"q": 1}
    assert answer["id"] == "np-widget" and answer["tag"] == "np" and answer["body"] == {"track": "Blue"}
    assert plugins.project_event(asked, ["link:provide"]) is not None
    assert plugins.project_event(answer, ["state:read"]) is None, "an answer reached a plugin without the grant"


async def test_a_plugin_reaches_no_channel_it_did_not_declare() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_pair(engine)
        await engine.handle({"cmd": "plugin.call", "id": "np-widget", "to": "spotify", "channel": "library", "req_id": 1})
        await engine.handle({"cmd": "plugin.call", "id": "spotify", "to": "np-widget", "channel": "now-playing", "req_id": 2})

    refused = [e for e in events if e.get("event") == "error" and e.get("req_id") in (1, 2)]
    assert len(refused) == 2, "an undeclared channel or a plugin with no link:consume got through"
    assert not any(e.get("event") == "call" for e in events)


async def test_an_answer_to_a_question_nobody_asked_is_refused() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_pair(engine)
        await engine.handle({"cmd": "plugin.answer", "id": "spotify", "call_id": "made-up", "body": {}, "req_id": 3})
        await engine.handle(
            {"cmd": "plugin.call", "id": "np-widget", "to": "spotify", "channel": "now-playing", "tag": "np"}
        )
        asked = next(e for e in events if e.get("event") == "call")
        await engine.handle({"cmd": "plugin.answer", "id": "np-widget", "call_id": asked["call_id"], "body": {}, "req_id": 4})

    refused = [e for e in events if e.get("event") == "error" and e.get("req_id") in (3, 4)]
    assert len(refused) == 2, "a made-up call id or the wrong plugin answered"


async def test_a_broadcast_only_reaches_the_plugins_that_asked_for_that_channel() -> None:
    platform = FakePlatform(infer_s=0.02)
    bystander = {**CONSUMER, "id": "elsewhere", "name": "Elsewhere", "consumes": ["spotify:library"]}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_pair(engine)
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(bystander)})
        await engine.handle(
            {"cmd": "plugin.update", "id": "elsewhere", "patch": {"granted": ["link:consume"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.publish", "id": "spotify", "channel": "now-playing", "body": {"track": "Blue"}})

    heard = [e for e in events if e.get("event") == "message"]
    assert [e["id"] for e in heard] == ["np-widget"]
    assert heard[0]["from"] == "spotify" and heard[0]["body"] == {"track": "Blue"}


async def test_a_disabled_provider_answers_nobody() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_pair(engine)
        await engine.handle({"cmd": "plugin.update", "id": "spotify", "patch": {"enabled": False}})
        await engine.handle(
            {"cmd": "plugin.call", "id": "np-widget", "to": "spotify", "channel": "now-playing", "req_id": 5}
        )

    assert any(e.get("event") == "error" and e.get("req_id") == 5 for e in events)


async def test_a_plugin_can_ask_for_a_picture_back_as_bytes() -> None:
    """A sandbox may show a picture it was handed but may not fetch one itself."""
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        await engine.handle({"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/art.jpg", "binary": True})

    assert platform.http_requests[-1]["binary"] is True
    assert any(e.get("event") == "http" for e in events)


async def test_a_sign_in_sends_the_user_back_to_the_loopback_address() -> None:
    """Providers refuse a redirect to the name, so the literal is what is sent."""
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "start", "origin": "http://localhost:8000"})
        opened = next(e for e in events if e.get("event") == "plugin_oauth")["url"]

    assert parse_qs(urlparse(opened).query)["redirect_uri"] == ["http://127.0.0.1:8000/oauth/callback"]


async def test_a_plugins_secrets_are_scrubbed_from_a_bug_report() -> None:
    """It never holds one, but PrintGuard puts them in requests it makes."""
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t-key"}})
        found = reports.collect_secrets(engine)
        scrubbed = reports.scrub("GET https://api.example.com/?k=s3cr3t-key failed", found)

    assert {"s3cr3t-key", "registered-app"} <= found
    assert "s3cr3t-key" not in scrubbed


async def test_plugin_state_view_carries_no_credentials() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await _register_printer(engine)
        view = plugins.project_state(engine.state_event(), ["state:read"])

    assert view["printers"][0]["name"] == "P"
    assert "config" not in view["printers"][0], "printer credentials reached a plugin"
    assert "settings" not in view and "tokens" not in view


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


async def test_a_plugin_ships_its_own_files_and_they_are_hashed_with_its_code() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "assets": ["icon.png", "table.json"]}
    files = {"icon.png": PNG, "table.json": b'{"a": 1}'}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest, files=files)})
        plugin = engine.plugins.get("demo")

    assert sorted(plugin.assets) == ["icon.png", "table.json"]
    assert plugin.digests["icon.png"] == hashlib.sha256(PNG).hexdigest()
    assert plugins.text_assets(plugin.assets) == {"table.json": '{"a": 1}'}, "an image reached the sandbox"


async def test_a_file_that_lies_about_what_it_is_never_installs() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "assets": ["icon.png"]}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "file"},
             "zip": plugin_zip(manifest, files={"icon.png": b"<script>alert(1)</script>"})}
        )

    assert engine.plugins.get("demo") is None, "a script wearing an image's name was installed"
    assert any(e.get("event") == "error" and "not really" in e["message"] for e in events)


def test_a_manifest_refuses_a_kind_of_file_a_plugin_may_not_ship() -> None:
    for name in ("payload.svg", "run.exe", "../escape.png", "alarm.mp3.exe"):
        with pytest.raises(ValueError):
            plugins.sanitise_manifest({**MANIFEST, "assets": [name]})


def test_a_platform_covers_its_own_variants_and_nothing_else() -> None:
    """A plugin naming a platform runs on the images built from it."""
    assert plugins.runs_here([], "macos"), "a plugin naming nowhere runs everywhere"
    assert plugins.runs_here(["docker"], "docker-nvidia")
    assert not plugins.runs_here(["docker-nvidia"], "docker")
    assert not plugins.runs_here(["docker", "windows"], "macos")


async def test_a_manifest_keeps_only_platforms_printguard_runs_on() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "platforms": ["windows", "toaster"]}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest)})
        record = engine.plugins.get("demo").public()

    assert record["manifest"]["platforms"] == ["windows"]


async def test_plugins_survive_a_restart() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine, granted=["state:read"])
        await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"config": {"picked": ["cam"]}}})

    restarted = Engine(platform)
    await restarted.start()
    try:
        restored = restarted.plugins.get("demo")
        assert restored.sources["plugin.js"] == PLUGIN_JS
        assert restored.config == {"picked": ["cam"]} and restored.granted == ["state:read"]
        await restarted.handle({"cmd": "plugin.remove", "id": "demo"})
        assert restarted.plugins.get("demo") is None
    finally:
        await restarted.stop()
