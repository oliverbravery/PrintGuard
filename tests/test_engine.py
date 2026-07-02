"""Engine simulation: fairness, frame dedup, standby gating, the watchdog
and the command protocol, all against an in-memory platform."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import numpy as np
from fakes import FakePlatform

from printguard.engine import vision, watchdog
from printguard.engine.engine import Engine
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
    assert any(urlparse(url).hostname == "api.telegram.org" and url.endswith("/sendPhoto") for _, url in platform.http_calls), "Telegram alert was never delivered"
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


async def test_provider_change_clears_stale_printer_state() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        engine.printers.get(printer_id).device_state = {"status": "printing", "progress": 1.0, "job": None}
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "Renamed"}})
        assert engine.printers.get(printer_id).device_state["status"] == "printing", "same provider must keep its state"

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://kl"}}})
        assert engine.printers.get(printer_id).device_state is None, "a new provider must not inherit the old state"


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


async def test_camera_add_rejects_webrtc_url() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.add", "name": "Cam", "source": {"kind": "url", "url": "http://pi/webcam/webrtc"}, "req_id": 5})
        assert engine.cameras.values() == [], "a WebRTC stream is never registered as a camera"
        assert any(e["event"] == "error" and e.get("req_id") == 5 and "WebRTC" in e["message"] for e in events)


async def test_printer_webrtc_camera_warns_instead_of_silently_skipping(monkeypatch) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        async def webrtc_cameras(http, config):
            return [{"key": "webcam", "name": "Chamber", "source": {"kind": "url", "url": "http://pi/webcam/webrtc"}}]

        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webrtc_cameras)
        await _register_printer(engine)
        await asyncio.sleep(0.1)  # printer.add reconciles its cameras in the background
        assert engine.cameras.values() == [], "a WebRTC feed exposed by a printer is not registered"
        assert any(e["event"] == "warning" and "WebRTC" in e["message"] for e in events), \
            "the user is told why a WebRTC feed was skipped rather than it silently no-opping"


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
        await engine.handle({"cmd": "settings.update", "patch": {"theme": "light"}})

    reborn = Engine(platform)
    await reborn.start()
    try:
        assert reborn.settings["theme"] == "light", "theme survives a restart"
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

    buckets, stats = history["buckets"], history["stats"]
    assert buckets and buckets[0]["n"] > 0, "no inference was folded into a bucket"
    assert stats["inferences"] == sum(b["n"] for b in buckets)
    assert stats["defect_frames"] > 0 and stats["defect_pct"] > 0, "sustained defect not counted"
    assert stats["alerts"] == 1 and len(snaps) == 1, "the cooldown holds a sustained defect to one alert and one snapshot"
    assert snaps[0]["action"] == "none" and snaps[0]["score"] >= 0.6, "snapshot carries the alert's action and score"
    assert base64.b64decode(snapshot["jpeg"]) == b"\xff\xd8fake", "snapshot bytes did not round-trip over the protocol"


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
