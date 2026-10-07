"""Engine simulation: fairness, frame dedup, standby gating, the watchdog
and the command protocol, all against an in-memory platform."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import struct
import threading
import time
import tracemalloc
import zipfile
import zlib
from urllib.parse import parse_qs, urlparse
from contextlib import asynccontextmanager

import numpy as np
import pytest
from fakes import FakePlatform

from printguard.engine import engine as engine_module
from printguard.engine import credentials, feedback, logs, oauth, plugins, reports, reviews, vision, watchdog
from printguard.engine.engine import EVENT_LOG_LEVELS, Engine
from printguard.engine.integrations import INTEGRATIONS, DeviceState, DeviceStatus
from printguard.engine.notifiers import NOTIFIERS
from printguard.engine.platform import Frame, Notice
from printguard.engine.registry import Camera
from printguard.engine.printers import PREHEAT_DEFAULTS

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


def _pushes(platform: FakePlatform) -> list[tuple[str, str]]:
    """The notifications that reached the ntfy channel the outage tests configure."""
    return [call for call in platform.http_calls if call[1] == "http://ntfy/topic"]


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


async def test_detection_rate_cap() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, _):
        camera = engine.cameras.values()[0]
        seen: list[float] = []
        original = engine.scheduler._on_result

        async def spy(cam, frame, result):
            seen.append(frame.seq)
            await original(cam, frame, result)

        engine.scheduler._on_result = spy
        await asyncio.sleep(0.5)
        uncapped = len(seen)
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"detect_fps": 2.0}})
        del seen[:]
        await asyncio.sleep(3.0)
        state = engine.state_event()["cameras"][0]

    assert uncapped > 4, f"an uncapped camera should run near its native rate, got {uncapped} in 0.5s"
    assert state["detect_fps"] == 2.0
    assert state["target_fps"] == 2.0, f"a capped camera should be allocated its cap, got {state['target_fps']}"
    rate = len(seen) / 3.0
    assert 1.0 <= rate <= 3.0, f"a capped camera should run near 2 fps, got {rate}"


async def test_a_cameras_image_adjustments_run_off_the_event_loop_and_count_as_latency(monkeypatch) -> None:
    transform = vision.transform
    threads: set[int] = set()

    def slow(rgb, **tuning):
        threads.add(threading.get_ident())
        time.sleep(0.05)
        return transform(rgb, **tuning)

    monkeypatch.setattr(vision, "transform", slow)
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, _):
        await asyncio.sleep(0.6)
        latency_ms = engine.scheduler.infer_ms

    assert threads and threading.get_ident() not in threads, "adjusting a frame held the event loop"
    assert latency_ms >= 50.0, f"capacity was worked out from inference alone: {latency_ms} ms"


async def test_a_capped_camera_does_not_slow_the_one_beside_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[30.0, 30.0]) as (engine, _):
        fast, capped = engine.cameras.values()
        await engine.handle({"cmd": "camera.update", "id": capped.id, "patch": {"detect_fps": 0.5}})
        seen: dict[str, list[float]] = {fast.id: [], capped.id: []}
        original = engine.scheduler._on_result

        async def spy(camera, frame, result):
            seen[camera.id].append(frame.seq)
            await original(camera, frame, result)

        await asyncio.sleep(0.5)
        engine.scheduler._on_result = spy
        await asyncio.sleep(3.0)
        target = fast.target_fps

    assert target == 30.0, f"the spare capacity should go to the uncapped camera, got {target}"
    fast_rate = len(seen[fast.id]) / 3.0
    assert fast_rate > 20.0, f"an uncapped camera beside a capped one should run near its 30 fps target, got {fast_rate}"
    assert len(seen[capped.id]) <= 3, f"a camera capped at 0.5 fps ran {len(seen[capped.id])} times in 3 s"
    assert seen[fast.id] == sorted(set(seen[fast.id])), "a frame was inferred twice or out of order"


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


async def test_a_test_alert_makes_the_request_a_defect_alert_does() -> None:
    """A channel can take text and refuse a picture, which a text-only test would not find."""
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {"url": "http://ntfy/topic"}, "req_id": 1}, events.append)
    (request,) = [request for request in platform.http_requests if request["url"] == "http://ntfy/topic"]
    assert request["method"] == "PUT" and request["headers"]["Filename"] == "snapshot.jpg"
    assert request["data"] == await platform.encode_jpeg(np.zeros((1, 1, 3), np.uint8))
    assert next(e for e in events if e.get("event") == "notify_test")["ok"]


async def test_a_plugins_notice_goes_out_quietly_and_a_test_alert_does_not() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _events):
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}, "pushover": {"api_token": "a", "user_key": "u"}}}})
        platform.http_requests.clear()
        await engine.handle({"cmd": "notify.send", "title": "Progress", "text": "Benchy is 50% done"})
        quiet = list(platform.http_requests)
        platform.http_requests.clear()
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {"url": "http://ntfy/topic"}, "req_id": 1})
        (test,) = platform.http_requests
    ntfy = next(request for request in quiet if request["url"] == "http://ntfy/topic")
    pushover = next(request for request in quiet if "pushover" in request["url"])
    assert "Priority" not in ntfy["headers"] and "Tags" not in ntfy["headers"]
    assert b"priority=0" in pushover["data"] or b'name="priority"\r\n\r\n0' in pushover["data"]
    assert test["headers"]["Priority"] == "urgent", "the test alert no longer tests the urgent path"


async def test_a_long_notice_title_is_cut_without_ending_in_a_space() -> None:
    platform = FakePlatform()
    title = "x" * 79 + " tail"
    async with running_engine(platform, camera_fps=[]) as (engine, _events):
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        platform.http_requests.clear()
        await engine.handle({"cmd": "notify.send", "title": title, "text": "x"})
    sent = next(request for request in platform.http_requests if request["url"] == "http://ntfy/topic")["headers"]["Title"]
    assert sent == title[:79], "a trailing space reaches the header, which h11 refuses"


@pytest.mark.parametrize("notice", [{"text": None}, {"text": ["a"]}, {"text": 0}, {"title": ["a"], "text": "x"}])
async def test_a_notice_that_is_not_text_is_refused(notice: dict) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _events):
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        with pytest.raises(RuntimeError, match="title and text are text"):
            await engine.request({"cmd": "notify.send", **notice})
    assert not _pushes(platform)


async def test_a_printer_and_a_notifier_never_follow_a_redirect() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _events):
        await engine.handle({"cmd": "printer.test", **OCTOPRINT, "req_id": 1})
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {"url": "http://ntfy/topic"}, "req_id": 2})
    asked = [request for request in platform.http_requests if request["url"].startswith(("http://ntfy/", "http://op/"))]
    assert {request["url"].split("/")[2] for request in asked} == {"ntfy", "op"}
    assert all(request["redirects"] == "refuse" for request in asked)


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


async def test_standby_gating(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.1)
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


async def test_switching_a_monitor_off_clears_its_alert_and_its_cameras_rate() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"threshold": 0.3, "consecutive": 1}})
        await asyncio.sleep(1.0)
        state = engine.state_event()
        assert state["monitors"][0]["alert"] and state["cameras"][0]["achieved_fps"] > 0

        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        state = engine.state_event()
        assert state["monitors"][0]["alert"] is None, "a monitor that is switched off still shows its defect"
        assert state["cameras"][0]["achieved_fps"] == 0, "a camera nothing watches still reports an inference rate"


async def test_lost_contact_keeps_the_last_reported_status(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.1}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.5)
        platform.device_status = "Offline"
        await asyncio.sleep(0.5)
        printer_warnings = lambda: [e for e in events if e.get("event") == "warning" and "Cannot tell whether the printer" in e["message"]]
        assert not engine.state_event()["monitors"][0]["watching"], "a printer switched off after a print must stay in standby"
        assert not engine.cameras.values()[0].in_use, "a printer switched off after a print must not wake the camera"
        assert not printer_warnings(), "a switched-off idle printer must not warn"

        platform.device_status = "Printing"
        await asyncio.sleep(0.5)
        platform.device_status = "Offline"
        await asyncio.sleep(0.5)
        assert engine.state_event()["monitors"][0]["watching"], "contact lost mid-print must keep watching"
        assert printer_warnings(), "contact lost mid-print must warn"


async def test_a_restart_remembers_the_printer_was_idle(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.1}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.5)

    platform.device_status = "Offline"
    restarted = Engine(platform)
    events: list[dict] = []
    await restarted.start()
    restarted.add_sink(events.append)
    await asyncio.sleep(0.5)
    watching = restarted.state_event()["monitors"][0]["watching"]
    await restarted.stop()
    assert not watching, "a hub restarted while an idle printer is switched off must stay in standby"
    assert not [e for e in events if e.get("event") == "warning"], "a hub restarted while an idle printer is switched off must not warn"


async def test_a_printer_command_regates_without_waiting_for_the_poll(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        camera = engine.cameras.values()[0]
        assert camera.in_use, "a printer not yet read should be watched"
        platform.device_status = "Paused"
        await engine.handle({"cmd": "printer.action", "id": printer_id, "action": "pause"})
        assert not camera.in_use, "pausing from PrintGuard must stand the camera down straight away"


async def test_a_command_that_worked_is_not_failed_by_the_read_after_it(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform()
    answer = platform.http

    async def drop_the_read_after_a_command(method: str, url: str, **kwargs):
        if method == "GET" and ("POST", "http://op/api/job") in platform.http_calls:
            raise ConnectionResetError("connection reset by peer")
        return await answer(method, url, **kwargs)

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        monkeypatch.setattr(platform, "http", drop_the_read_after_a_command)
        await engine.request({"cmd": "printer.action", "id": printer_id, "action": "pause"})
    assert platform.http_calls.count(("POST", "http://op/api/job")) == 1


async def test_an_error_that_says_nothing_is_reported_by_its_type(monkeypatch) -> None:
    platform = FakePlatform()

    async def time_out(method: str, url: str, **kwargs):
        raise TimeoutError

    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        monkeypatch.setattr(platform, "http", time_out)
        await engine.handle({"cmd": "printer.action", "id": printer_id, "action": "pause", "req_id": 4})
        await engine.handle({"cmd": "printer.test", **OCTOPRINT}, events.append)
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {"url": "http://ntfy/topic"}}, events.append)
        assert next(e for e in events if e["event"] == "error" and e.get("req_id") == 4)["message"] == "TimeoutError"
        assert next(e for e in events if e["event"] == "printer_test")["error"] == "TimeoutError"
        assert next(e for e in events if e["event"] == "notify_test")["error"] == "TimeoutError"


def _of(events: list[dict], kind: str) -> list[dict]:
    return [event for event in events if event.get("event") == kind]


async def _disk_full(*_args, **_kwargs) -> int:
    raise OSError(28, "No space left on device")


NTFY = {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}


async def test_a_full_disk_does_not_stop_detection(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    monkeypatch.setattr(platform.files, "store", _disk_full)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": NTFY})
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"notify": True}})
        await asyncio.sleep(1.5)

    errors = [event["message"] for event in _of(events, "error")]
    assert _of(events, "result") and _of(events, "alert"), "a frame that cannot be kept for review is still scored"
    assert _pushes(platform), "the alert is pushed before its frame is stored"
    assert any("for review failed" in message for message in errors), "the failed sample is reported as what it is"
    assert any("defect response" in message for message in errors), "the alert frame that could not be stored is reported"
    assert not any("inference failed" in message for message in errors)
    assert len(errors) <= 2, "a fault that repeats on every frame is not reported on every frame"


async def test_a_runtime_returning_non_finite_embeddings_is_an_inference_error_not_a_quiet_success() -> None:
    assets = vision.Assets(mean=(0.5,), std=(0.5,), prototypes={"success": np.zeros(8, np.float32), "failure": np.ones(8, np.float32)})

    class NanPlatform(FakePlatform):
        async def infer(self, rgb: np.ndarray) -> dict:
            await asyncio.sleep(0.01)
            return vision.classify(np.full(8, np.nan, np.float32), assets)

    async with running_engine(NanPlatform(), camera_fps=[15.0]) as (engine, events):
        await asyncio.sleep(0.8)
        camera = engine.cameras.values()[0]

    errors = [event["message"] for event in _of(events, "error")]
    assert len(errors) == 1 and "non-finite embedding" in errors[0], "a fault on every frame is reported once"
    assert not _of(events, "result") and not camera.last_result, "a frame with no embedding was scored as a success"


async def test_a_failed_save_does_not_end_printer_polling(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(engine_module, "LOOP_RETRY_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.3)
        save_state = platform.save_state

        def failing_save(state: dict) -> None:
            raise OSError(28, "No space left on device")

        platform.save_state = failing_save
        platform.device_status = "Operational"
        await asyncio.sleep(0.3)
        platform.save_state = save_state
        platform.device_status = "Printing"
        await asyncio.sleep(0.3)
        watching = engine.state_event()["monitors"][0]["watching"]

    assert any("saving the state failed" in event["message"] for event in _of(events, "error")), "a failed save is reported"
    assert watching, "the next print is noticed after a poll failed"


async def test_a_monitor_whose_camera_is_gone_warns_and_gets_it_back(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    device = {"kind": "device", "device_id": "/dev/video0", "label": "C920", "declared": True}
    platform = FakePlatform(infer_s=0.02)
    platform.devices = [device]
    engine = Engine(platform)
    await engine.start()
    camera_id = engine.cameras.values()[0].id
    await engine.handle({"cmd": "settings.update", "patch": {**NTFY, "fault_grace_s": 0.1}})
    await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": camera_id, "notify": True}})
    monitor_id = next(iter(engine.monitors))
    await engine.stop()

    platform.devices = [{**device, "declared": False}]
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)
    await asyncio.sleep(0.5)
    await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": "renamed"}})
    unwatched = engine.state_event()["monitors"][0]
    await engine.stop()
    assert unwatched["enabled"] and not unwatched["watching"], "a monitor with no camera does not read as watching"
    assert any("has no camera" in event["message"] for event in _of(events, "warning")) and _pushes(platform)
    assert platform.state["monitors"][0]["camera_id"] == camera_id, "the binding outlives the boot the device was not declared at"

    platform.devices = [device]
    engine = Engine(platform)
    events = []
    await engine.start()
    engine.add_sink(events.append)
    await asyncio.sleep(0.5)
    watched = engine.state_event()["monitors"][0]
    await engine.stop()
    assert watched["watching"] and _of(events, "result"), "the monitor watches again once its device is back"


async def test_a_printer_camera_keeps_its_monitor_through_a_provider_change(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    monkeypatch.setattr(INTEGRATIONS["klipper"], "cameras", webcam)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)
        monitor_id = next(iter(engine.monitors))
        own_camera = engine.monitors[monitor_id]["camera_id"]
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"camera_id": f"{printer_id}-webcam"}})
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://kl"}}})
        await asyncio.sleep(0.1)
        camera = engine.cameras.get(f"{printer_id}-webcam")
        assert camera is not None and camera.in_use, "the camera registered again under its id is watched again"
        assert engine.state_event()["monitors"][0]["watching"]

        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"camera_id": own_camera}})
        await engine.handle({"cmd": "camera.remove", "id": own_camera})
        assert engine.monitors[monitor_id]["camera_id"] == "", "a camera the user removed takes its binding with it"


async def test_a_monitor_binding_is_always_stored_as_text() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        camera_id = engine.monitors[monitor_id]["camera_id"]
        with pytest.raises(RuntimeError, match="camera_id is text"):
            await engine.request({"cmd": "monitor.update", "id": monitor_id, "patch": {"camera_id": [], "printer_id": {}}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": "renamed"}, "req_id": 2})
        assert not [event for event in _of(events, "error") if event.get("req_id") == 2], "a bad binding does not break later commands"
        assert (engine.monitors[monitor_id]["camera_id"], engine.monitors[monitor_id]["printer_id"]) == (camera_id, "")

    restarted = Engine(platform)
    await restarted.start()
    await restarted.stop()


async def test_a_monitor_that_stands_down_forgets_its_camera_fault(monkeypatch) -> None:
    from fakes import FakeSource

    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 0.5)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 1.0}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.3)
        source = engine.cameras.values()[0].frame_source
        source.online = False
        await asyncio.sleep(0.2)
        platform.device_status = "Operational"
        await asyncio.sleep(1.5)

        def slow_wake(self: FakeSource, active: bool) -> None:
            self.standby = not active
            self.online = False
            if active:
                asyncio.get_running_loop().call_later(0.2, lambda: setattr(self, "online", True))

        monkeypatch.setattr(FakeSource, "set_monitoring", slow_wake)
        released = len(platform.released_cameras)
        platform.device_status = "Printing"
        await asyncio.sleep(0.45)
        assert not _of(events, "warning"), "a blip from the last print does not count against the next one"
        assert len(platform.released_cameras) == released, "a camera that is waking up is not torn down"


async def test_a_defect_response_is_sent_once_with_no_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    platform.action_delay_s = 0.2
    answer = platform.http

    async def pausing(method: str, url: str, **request) -> tuple[int, object]:
        response = await answer(method, url, **request)
        if method == "POST" and "/api/job" in url:
            platform.device_status = "Paused"
        return response

    monkeypatch.setattr(platform, "http", pausing)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 0, "consecutive": 1}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(1.2)
        monitor = engine.state_event()["monitors"][0]

    commands = [call for call in platform.http_calls if call[0] == "POST" and "/api/job" in call[1]]
    assert len(commands) == 1, "a paused print is not sent the command again"
    assert not monitor["watching"] and monitor["alert"], "the pause stands the monitor down with its alert showing"


@pytest.mark.parametrize("read_back", ["fails", "says_unknown"])
async def test_a_taken_command_is_not_resent_when_the_read_back_does_not_show_it(monkeypatch, read_back: str) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http
    pause_taken = False

    async def pausing(method: str, url: str, **request) -> tuple[int, object]:
        nonlocal pause_taken
        if method == "POST" and "/api/job" in url:
            pause_taken = True
        elif pause_taken and method == "GET":
            if read_back == "fails":
                raise RuntimeError("busy")
            platform.device_status = "Mystery"
        return await answer(method, url, **request)

    monkeypatch.setattr(platform, "http", pausing)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.watchdog.poll_devices()
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 0, "consecutive": 1}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(1.2)
        printer = engine.state_event()["printers"][0]

    commands = [call for call in platform.http_calls if call[0] == "POST" and "/api/job" in call[1]]
    assert len(commands) == 1, "a command the printer took is not sent again every frame"
    assert len(_of(events, "alert")) == 1
    assert printer["online"] or read_back == "says_unknown", "a failed read after a command that went through does not take the printer offline"


async def test_a_camera_dropout_ends_the_defect_streak() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.inference_blocked = True
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        monitor = next(iter(engine.monitors.values()))
        camera = next(iter(engine.cameras.values()))
        await engine.handle({"cmd": "monitor.update", "id": monitor["id"], "patch": {"consecutive": 3, "notify": False}})
        monitor = engine.monitors[monitor["id"]]
        frame = Frame(rgb=np.zeros((48, 64, 3), np.uint8), seq=0.0, ts=time.time())
        await engine.watchdog.on_score(monitor, frame, 0.99)
        await engine.watchdog.on_score(monitor, frame, 0.99)
        camera.frame_source.online = False
        await engine.watchdog.watch_health()
        await engine.watchdog.on_score(monitor, frame, 0.99)
        await asyncio.sleep(0)

    assert not _of(events, "alert"), "two defect frames before a dropout and one after are not three in a row"


async def test_a_camera_dropped_and_registered_again_ends_the_defect_streak() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.inference_blocked = True
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        monitor = next(iter(engine.monitors.values()))
        camera = next(iter(engine.cameras.values()))
        await engine.handle({"cmd": "monitor.update", "id": monitor["id"], "patch": {"consecutive": 3, "notify": False}})
        monitor = engine.monitors[monitor["id"]]
        frame = Frame(rgb=np.zeros((48, 64, 3), np.uint8), seq=0.0, ts=time.time())
        await engine.watchdog.on_score(monitor, frame, 0.99)
        await engine.watchdog.on_score(monitor, frame, 0.99)
        await engine._drop_camera(camera.id)
        await engine.watchdog.watch_health()
        engine.cameras.add(camera)
        await engine.watchdog.on_score(monitor, frame, 0.99)
        await asyncio.sleep(0)

    assert not _of(events, "alert"), "two defect frames before the camera went and one after it came back are not three in a row"


async def test_a_removed_monitor_leaves_nothing_behind_in_the_watchdog() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off", **NTFY}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        await asyncio.sleep(0.8)
        assert _of(events, "alert")
        await engine.handle({"cmd": "monitor.remove", "id": monitor_id})
        held = [value for value in vars(engine.watchdog).values() if isinstance(value, (dict, set))]

    assert not any(monitor_id in key or (isinstance(key, tuple) and monitor_id in key) for container in held for key in container)


async def test_a_streak_does_not_survive_the_monitor_being_switched_off() -> None:
    platform = FakePlatform(infer_s=0.05, failing=True)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"consecutive": 30}})
        await asyncio.sleep(1.2)
        assert not _of(events, "alert")
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
        await asyncio.sleep(1.0)
        assert not _of(events, "alert"), "defect frames counted before the monitor was switched off are not counted again"


async def test_an_alert_reaches_a_monitor_edited_while_its_printer_was_answering() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.action_delay_s = 0.3
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id, "on_defect": "pause"}})
        await asyncio.wait_for(platform.action_started.wait(), 2.0)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": "renamed"}})
        await asyncio.sleep(0.6)
        assert engine.state_event()["monitors"][0]["alert"], "the alert shows on the monitor as it is now"


async def test_a_monitor_removed_while_its_printer_was_answering_leaves_nothing_behind() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.action_delay_s = 0.3
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id, "on_defect": "pause"}})
        await asyncio.wait_for(platform.action_started.wait(), 2.0)
        await engine.handle({"cmd": "monitor.remove", "id": monitor_id})
        await asyncio.sleep(0.6)
        assert not _of(events, "alert") and not engine.history and not engine.state_event()["reviews"]


def _answering(platform: FakePlatform, command) -> None:
    """Has the printer do something more when it is sent a pause or cancel.

    Args:
        platform: The platform whose printer it is.
        command: Awaited with the usual answer still to come, once per pause or cancel.
    """
    answer = platform.http

    async def http(method: str, url: str, **request) -> tuple[int, object]:
        if method == "POST" and "/api/job" in url:
            await command()
        return await answer(method, url, **request)

    platform.http = http


async def test_an_alert_shows_on_a_monitor_a_poll_stood_down_while_its_printer_was_answering(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)

    async def pausing() -> None:
        platform.device_status = "Pausing"
        await asyncio.sleep(0.3)

    _answering(platform, pausing)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(1.0)
        monitor = engine.state_event()["monitors"][0]

    assert [alert["action"] for alert in _of(events, "alert")] == ["pause"]
    assert not monitor["watching"] and monitor["alert"], "the print PrintGuard paused shows no alert"


async def test_the_status_read_after_a_defect_response_is_saved(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)

    async def paused() -> None:
        platform.device_status = "Paused"

    _answering(platform, paused)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, _):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id, "on_defect": "pause"}})
        platform.failing = True
        await asyncio.sleep(1.0)
        assert engine.printers.get(printer_id).reported_status == "paused"
        assert platform.state["printers"][0]["reported_status"] == "paused", "a restart would find the paused printer printing"


async def test_a_cooldown_ends_with_the_print_that_set_it(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)

    async def cancelled() -> None:
        platform.device_status = "Operational"

    _answering(platform, cancelled)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "cancel", "cooldown_s": 600}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(0.8)
        assert len(_of(events, "alert")) == 1 and not engine.state_event()["monitors"][0]["watching"]
        platform.device_status = "Printing"
        await asyncio.sleep(0.8)

    assert len(_of(events, "alert")) == 2, "the next print failed inside the last one's cooldown and nothing was done"


async def test_a_print_resumed_inside_the_cooldown_is_not_paused_again(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)

    async def paused() -> None:
        platform.device_status = "Paused"

    _answering(platform, paused)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 600}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(0.8)
        platform.device_status = "Printing"
        await asyncio.sleep(0.8)
        assert engine.state_event()["monitors"][0]["watching"]

    assert len(_of(events, "alert")) == 1, "resuming after a false alarm paused the print again at once"


async def test_a_command_the_printer_refused_is_tried_again_inside_the_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    monkeypatch.setattr(watchdog, "ACT_FAILED_COOLDOWN_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.reject_actions = True
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 600}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await asyncio.sleep(1.0)

    failed = [alert for alert in _of(events, "alert") if alert["action"] == "failed"]
    assert len(failed) >= 2, "a pause that failed was not tried again until the cooldown was up"


async def test_a_refused_command_waits_the_failed_cooldown_even_with_no_cooldown_of_its_own(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    monkeypatch.setattr(watchdog, "ACT_FAILED_COOLDOWN_S", 0.5)
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.reject_actions = True
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 0, "consecutive": 1}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await asyncio.sleep(1.2)

    failed = [alert for alert in _of(events, "alert") if alert["action"] == "failed"]
    assert 1 <= len(failed) <= 3, "a refused command was sent again at the monitor's own cooldown of none"


async def test_a_defect_in_the_first_seconds_of_uptime_is_still_pushed(monkeypatch) -> None:
    real_monotonic = time.monotonic
    booted = real_monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() - booted + 8.0)
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off", **NTFY}})
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"notify": True}})
        await asyncio.sleep(1.0)

    assert _of(events, "alert") and _pushes(platform), "an alert raised soon after the host booted was never pushed"


async def test_a_full_disk_between_pause_attempts_does_not_lose_the_alert(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    platform = FakePlatform(infer_s=0.02)
    platform.reject_actions = True
    answer = platform.http

    async def stopping_by_itself(method: str, url: str, **request) -> tuple[int, object]:
        if method == "POST" and "/api/job" in url:
            platform.device_status = "Error"
        return await answer(method, url, **request)

    monkeypatch.setattr(platform, "http", stopping_by_itself)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off", **NTFY}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1, "notify": True}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await engine.watchdog.poll_devices()

        def failing_save(state: dict) -> None:
            raise OSError(28, "No space left on device")

        platform.save_state = failing_save
        platform.failing = True
        await asyncio.sleep(1.0)

    assert _of(events, "alert") and _pushes(platform), "a failed save between attempts swallowed the alert"
    assert any("saving the state failed" in event["message"] for event in _of(events, "error")), "the full disk went unreported"


async def test_a_pause_that_worked_is_pushed_straight_after_one_that_failed(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    monkeypatch.setattr(watchdog, "ACT_FAILED_COOLDOWN_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    attempts = 0

    async def third_time_lucky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts <= watchdog.ACT_ATTEMPTS:
            raise RuntimeError("timed out")
        platform.device_status = "Paused"

    _answering(platform, third_time_lucky)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off", **NTFY}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "cooldown_s": 0, "notify": True}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        platform.failing = True
        await asyncio.sleep(1.0)

    pushed = [request["headers"]["Message"] for request in platform.http_requests if request["url"] == "http://ntfy/topic"]
    assert [alert["action"] for alert in _of(events, "alert")] == ["failed", "pause"]
    assert pushed == ["AUTOMATIC PAUSE FAILED, check the printer", "Action taken: pause"], "the last push says the pause failed when it worked"


async def test_a_monitor_removed_while_its_alert_was_being_pushed_leaves_nothing_behind() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    answer = platform.http
    pushing = asyncio.Event()

    async def slow_push(method: str, url: str, **request) -> tuple[int, object]:
        if url == "http://ntfy/topic":
            pushing.set()
            await asyncio.sleep(0.3)
        return await answer(method, url, **request)

    platform.http = slow_push
    async with running_engine(platform, camera_fps=[15.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": NTFY})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        await asyncio.wait_for(pushing.wait(), 2.0)
        await engine.handle({"cmd": "monitor.remove", "id": monitor_id})
        await asyncio.sleep(0.6)
        assert not engine.history and not engine.state_event()["reviews"] and not platform.files.blobs


async def test_a_monitor_removed_while_its_frame_was_being_stored_leaves_nothing_behind() -> None:
    platform = FakePlatform(infer_s=0.02)
    store = platform.files.store
    storing = asyncio.Event()

    async def slow_store(key: str, chunks) -> int:
        storing.set()
        await asyncio.sleep(0.2)
        return await store(key, chunks)

    platform.files.store = slow_store
    async with running_engine(platform, camera_fps=[15.0]) as (engine, _):
        await asyncio.wait_for(storing.wait(), 2.0)
        await engine.handle({"cmd": "monitor.remove", "id": next(iter(engine.monitors))})
        await asyncio.sleep(0.4)
        assert not engine.state_event()["reviews"] and not platform.files.blobs, "the frame outlived the review it was for"


async def test_a_channel_that_never_answers_holds_up_neither_the_others_nor_the_monitor(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "NOTIFY_TIMEOUT_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    answer = platform.http

    async def silent(method: str, url: str, **request) -> tuple[int, object]:
        if url == "http://ntfy/topic":
            await asyncio.Event().wait()
        return await answer(method, url, **request)

    platform.http = silent
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        notifiers = {"ntfy": {"url": "http://ntfy/topic"}, "discord": {"webhook_url": "http://disc/hook"}}
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": notifiers}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        await asyncio.sleep(1.0)
        assert monitor_id not in engine.watchdog.responding, "the monitor can never respond to a defect again"

    assert ("POST", "http://disc/hook") in platform.http_calls, "the channel behind the silent one was never sent to"
    assert any(message.startswith("Sending to ntfy failed") for message in (event["message"] for event in _of(events, "error")))


async def test_overlapping_reconciles_open_a_printer_camera_once(monkeypatch) -> None:
    platform = FakePlatform()
    opened: list[str] = []
    open_camera = platform.open_camera

    async def slow_open(camera_id: str, source: dict):
        opened.append(camera_id)
        await asyncio.sleep(0.2)
        return await open_camera(camera_id, source)

    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0}}]

    monkeypatch.setattr(platform, "open_camera", slow_open)
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await _register_printer(engine)
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "printer.cameras.refresh"})
        assert len(opened) == 1 and len(engine.cameras.values()) == 1, "a refresh during the first open does not open the camera again"


def _slow_printer_webcam(platform: FakePlatform, monkeypatch) -> None:
    """Gives OctoPrint a webcam that takes a moment to open, as a real stream does."""
    open_camera = platform.open_camera

    async def slow_open(camera_id: str, source: dict):
        if camera_id.endswith("-webcam"):
            await asyncio.sleep(0.2)
        return await open_camera(camera_id, source)

    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0}}]

    monkeypatch.setattr(platform, "open_camera", slow_open)
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)


async def test_a_printer_removed_while_its_camera_opens_leaves_no_camera_behind(monkeypatch) -> None:
    platform = FakePlatform()
    _slow_printer_webcam(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "printer.remove", "id": printer_id})
        await asyncio.sleep(0.3)
        assert engine.cameras.values() == [] and platform.state["cameras"] == []
        assert platform.released_cameras == [f"{printer_id}-webcam"], "the stream it opened is closed again"


async def test_stopping_while_a_printer_camera_opens_keeps_the_other_cameras_saved(monkeypatch) -> None:
    platform = FakePlatform()
    _slow_printer_webcam(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await _register_printer(engine)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)
    assert [camera["name"] for camera in platform.state["cameras"]] == ["cam10.0"]


async def test_a_printer_camera_follows_its_printers_new_address(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0, "url": f"{config['base_url']}/stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)
        camera = engine.cameras.values()[0]
        first_source = camera.frame_source
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"name": "Nozzle", "rotation": 180}})
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://moved", "api_key": "k"}}})
        await asyncio.sleep(0.1)
        assert engine.cameras.values() == [camera] and camera.source["url"] == "http://moved/stream"
        assert (camera.name, camera.rotation) == ("Nozzle", 180), "the camera keeps its name and tuning"
        assert camera.id in platform.released_cameras and not first_source.online, "the old source is closed"
        assert camera.frame_source not in (None, first_source), "the camera is attached again at the new address"


@pytest.mark.parametrize("taken_down_by", ["a move to a new address", "a restart"])
async def test_the_reattach_tick_leaves_a_camera_alone_while_it_is_taken_down(monkeypatch, taken_down_by: str) -> None:
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    monkeypatch.setattr(engine_module, "REATTACH_EVERY_TICKS", 1)

    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0, "url": f"{config['base_url']}/stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)

    class SlowRelease(FakePlatform):
        opened: list[str] = []
        release_s = 0.0

        async def open_camera(self, camera_id, source):
            self.opened.append(source["url"])
            return await super().open_camera(camera_id, source)

        async def release_camera(self, camera_id, source):
            await asyncio.sleep(self.release_s)
            await super().release_camera(camera_id, source)

    platform = SlowRelease()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.2)
        camera = engine.cameras.values()[0]
        platform.opened.clear()
        platform.release_s = 0.4
        if taken_down_by == "a restart":
            await engine.restart_camera(camera)
        else:
            await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://moved", "api_key": "k"}}})
        await asyncio.sleep(1.0)

    expected = "http://op/stream" if taken_down_by == "a restart" else "http://moved/stream"
    assert platform.opened == [expected], "the camera was opened more than once, or at the address it was leaving"


async def test_a_camera_moved_while_it_restarts_is_opened_at_the_new_address_only(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0, "url": f"{config['base_url']}/stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)

    class SlowRelease(FakePlatform):
        opened: list[str] = []
        release_s = 0.0

        async def open_camera(self, camera_id, source):
            self.opened.append(source["url"])
            return await super().open_camera(camera_id, source)

        async def release_camera(self, camera_id, source):
            await asyncio.sleep(self.release_s)
            await super().release_camera(camera_id, source)

    platform = SlowRelease()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.2)
        camera = engine.cameras.values()[0]
        platform.opened.clear()
        platform.release_s = 0.3
        restart = asyncio.create_task(engine.restart_camera(camera))
        await asyncio.sleep(0.1)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://moved", "api_key": "k"}}})
        await restart
        await asyncio.sleep(0.5)
        assert camera.source["url"] == "http://moved/stream"
        assert platform.opened == ["http://moved/stream"], "the restart opened the camera at the address it was leaving"


async def test_refresh_keeps_a_printer_camera_that_works_and_moves_one_that_does_not(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "CAMERA_SETTLE_S", 0.3)

    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0, "url": "http://op/webcam"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": camera.id}})
        camera.source = {"kind": "fake", "fps": 20.0, "url": "http://op:5000/webcam"}
        await engine.handle({"cmd": "printer.cameras.refresh"})
        assert camera.source["url"] == "http://op:5000/webcam", "a camera that delivers frames was moved to an address that may be wrong"
        camera.frame_source.online = False
        await engine.handle({"cmd": "printer.cameras.refresh"})
        assert camera.source["url"] == "http://op/webcam", "a camera that delivers nothing stayed at an address that does not work"
        assert camera.printer_id == printer_id


async def test_a_printer_that_answers_after_boot_has_its_cameras_listed_once(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "CAMERA_SETTLE_S", 0.1)
    asked: list[str] = []

    async def webcam(http, config):
        asked.append(config["base_url"])
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 20.0, "url": "http://op/webcam"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    platform = FakePlatform()
    platform.state = {
        "printers": [{"id": "p1", "name": "P", "provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}],
        "cameras": [{"id": "p1-webcam", "name": "Shop cam", "source": {"kind": "device", "device_id": "/dev/gone"}, "printer_id": "p1", "max_fps": 15.0}],
    }
    platform.responses["http://op/api/job"] = (500, {})
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.watchdog.refresh(engine.printers.get("p1"))
        await asyncio.sleep(0.3)
        assert asked == [] and not _of(events, "warning"), "a printer that was switched off at boot was asked for its cameras"
        del platform.responses["http://op/api/job"]
        await engine.watchdog.refresh(engine.printers.get("p1"))
        await asyncio.sleep(0.4)
        assert asked == ["http://op"] and engine.cameras.get("p1-webcam").source["url"] == "http://op/webcam", "the camera kept the address it was saved at"
        await engine.watchdog.refresh(engine.printers.get("p1"))
        await asyncio.sleep(0.2)
        assert asked == ["http://op"], "the printer was asked again after it had answered"


async def test_testing_a_printer_closes_the_connection_it_opened(monkeypatch) -> None:
    closed: list[dict | None] = []

    async def close(config=None):
        closed.append(config)

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "close", close)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        untried = {"base_url": "http://other", "api_key": "k"}
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "config": untried}, events.append)
        assert closed == [untried], "a test of unregistered details leaves no connection open"
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "config": engine.printers.get(printer_id).config}, events.append)
        assert closed == [untried], "a registered printer keeps its connection"
        assert [event["ok"] for event in _of(events, "printer_test")] == [True, True]


async def test_testing_from_the_edit_form_keeps_the_connection_the_printer_is_using(monkeypatch) -> None:
    """The form sends every field, so its config differs from the stored one by a blank it added."""
    closed: list[dict | None] = []

    async def close(config=None):
        closed.append(config)

    async def idle(http, config):
        return DeviceState(DeviceStatus.IDLE)

    async def no_cameras(http, config):
        return []

    elegoo = INTEGRATIONS["elegoo"]
    for name, stub in (("close", close), ("fetch_state", idle), ("cameras", no_cameras)):
        monkeypatch.setattr(elegoo, name, stub)
    stored = {"family": "centauri", "host": "10.0.0.9", "access_code": "Ab3dEf"}
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", "provider": "elegoo", "config": stored}})
        await engine.handle({"cmd": "printer.test", "provider": "elegoo", "config": {**stored, "api_key": ""}}, events.append)
        assert closed == [], "the test closed the connection the registered printer polls over"
        elsewhere = {**stored, "host": "10.0.0.10"}
        await engine.handle({"cmd": "printer.test", "provider": "elegoo", "config": elsewhere}, events.append)
        assert closed == [elsewhere]
        closed.clear()
        await engine.handle({"cmd": "printer.update", "id": next(iter(engine.printers.items)), "patch": {"config": {**stored, "family": "moonraker"}}})
        closed.clear()
        await engine.handle({"cmd": "printer.test", "provider": "elegoo", "config": stored})
        assert closed == [stored], "a Centauri test beside a printer registered as Moonraker left its connection open"


async def test_a_requested_action_waits_as_long_as_the_printers_service_can_take(monkeypatch) -> None:
    """A Centauri Carbon 2 answers a resume only once it has reheated and unparked."""

    async def slow_send(http, config, action):
        await asyncio.sleep(0.1)

    monkeypatch.setattr(engine_module, "REQUEST_TIMEOUT_S", 0.05)
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "send", slow_send)
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        with pytest.raises(asyncio.TimeoutError):
            await engine.request({"cmd": "printer.action", "id": printer_id, "action": "resume"})
        monkeypatch.setattr(INTEGRATIONS["octoprint"], "slow_action_s", 5.0, raising=False)
        await engine.request({"cmd": "printer.action", "id": printer_id, "action": "resume"})
        assert INTEGRATIONS["elegoo"].slow_action_s == 90.0, "pycentauri gives a Centauri Carbon 2 this long to answer"


@pytest.mark.parametrize("command", ["printer.action", "printer.heat"])
async def test_a_printer_command_with_an_id_that_is_not_text_fails_as_any_command_does(command: str) -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        with pytest.raises(RuntimeError):
            await engine.request({"cmd": command, "id": ["p"], "action": "resume"})
        assert _of(events, "error"), "the transport was handed the exception with no error event"


@pytest.mark.parametrize(
    ("provider", "partial", "blank"),
    [
        ("bambu", {"host": "10.0.0.9", "access_code": "12345678"}, "Serial number"),
        ("elegoo", {"host": "10.0.0.9"}, "Printer family"),
        ("octoprint", {"base_url": "http://op", "api_key": " "}, "API key"),
    ],
)
async def test_a_printer_missing_a_required_field_is_refused_by_name(provider: str, partial: dict, blank: str) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", "provider": provider, "config": partial}})
        assert not engine.printers.values() and not platform.state.get("printers")
        assert blank in _of(events, "error")[-1]["message"]

        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": provider, "config": partial}})
        assert engine.printers.get(printer_id).provider == "octoprint", "the printer keeps the details that worked"
        assert blank in _of(events, "error")[-1]["message"]

        errors = len(_of(events, "error"))
        await engine.handle({"cmd": "printer.test", "provider": provider, "config": partial}, events.append)
        (tested,) = _of(events, "printer_test")
        assert not tested["ok"] and blank in tested["error"]
        assert len(_of(events, "error")) == errors, "a failed test is reported once"


async def test_an_alert_channel_missing_a_required_field_is_refused_by_name() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"telegram": {"bot_token": "t"}}}})
        assert not engine.settings["notifiers"] and "Chat ID" in _of(events, "error")[-1]["message"]

        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {}}, events.append)
        (tested,) = _of(events, "notify_test")
        assert not tested["ok"] and "Topic URL" in tested["error"] and not _pushes(platform)


async def test_a_printer_edited_while_it_was_being_read_drops_the_old_address_answer() -> None:
    platform = FakePlatform()
    answering, held = asyncio.Event(), asyncio.Event()

    async def fetch_state(http, config):
        if config["base_url"] != "http://old":
            raise ConnectionError("unreachable")
        answering.set()
        await held.wait()
        return DeviceState(DeviceStatus.IDLE)

    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        printer = engine.printers.get(printer_id)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://old", "api_key": "k"}}})
        adapter = INTEGRATIONS[printer.provider]
        original, adapter.fetch_state = adapter.fetch_state, fetch_state
        try:
            reading = asyncio.ensure_future(engine.watchdog._read(printer))
            await answering.wait()
            await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://new", "api_key": "k"}}})
            held.set()
            assert not await reading and printer.reported_status is None
        finally:
            adapter.fetch_state = original


@pytest.mark.parametrize(
    ("provider", "partial", "completed"),
    [
        ("bambu", {"host": "10.0.0.9", "access_code": "12345678"}, {"serial": "01S00A"}),
        ("elegoo", {"host": "10.0.0.9"}, {"family": "moonraker"}),
        ("elegoo", {"family": "centauri"}, {"host": "10.0.0.9"}),
    ],
)
async def test_a_printer_saved_without_a_required_field_can_be_completed_or_removed(
    monkeypatch, provider: str, partial: dict, completed: dict
) -> None:
    """2.5.0 saved these, and closing their connection raised before the edit or the removal was kept."""

    async def offline(http, config):
        return DeviceState(DeviceStatus.OFFLINE)

    async def no_cameras(http, config):
        return []

    monkeypatch.setattr(INTEGRATIONS[provider], "fetch_state", offline)
    monkeypatch.setattr(INTEGRATIONS[provider], "cameras", no_cameras)
    saved = {
        "printers": [{"id": "old", "name": "P", "provider": provider, "config": partial}],
        "monitors": [{"id": "m", "name": "M", "printer_id": "old"}],
    }
    platform = FakePlatform()
    platform.state = json.loads(json.dumps(saved))
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "printer.update", "id": "old", "patch": {"config": {**partial, **completed}}})
        assert engine.printers.get("old").config == {**partial, **completed}
        assert platform.state["printers"][0]["config"] == {**partial, **completed}
        await engine.handle({"cmd": "printer.update", "id": "old", "patch": {"config": partial}})
        assert engine.printers.get("old").config == {**partial, **completed}

    platform = FakePlatform()
    platform.state = saved
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "printer.remove", "id": "old"})
        assert platform.state["printers"] == [] and platform.state["monitors"][0]["printer_id"] == ""
        assert not _of(events, "error")


async def test_reading_history_neither_saves_nor_broadcasts_state() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        saves: list[dict] = []
        platform.save_state = saves.append
        asked: list[dict] = []
        await engine.handle({"cmd": "history.get", "monitor_id": "none", "req_id": 7}, asked.append)
        assert [event["event"] for event in asked] == ["history"]
        assert not [event for event in events if event.get("req_id") == 7], "a read was answered to a transport that did not ask"
        assert not saves, "a command that changes nothing writes nothing"
        heard: list[dict] = []
        answered = await engine.request({"cmd": "history.get", "monitor_id": "none"}, reply=heard.append)
        assert [event["event"] for event in answered] == ["history"]
        assert heard == answered, "a hub plugin hears the answer to its own read"


async def test_a_command_that_changes_nothing_stored_saves_nothing_and_answers_only_its_issuer() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        saves: list[dict] = []
        platform.save_state = saves.append
        asked: list[dict] = []
        await engine.handle({"cmd": "discover", "req_id": 7}, asked.append)
        assert [(event["event"], event["req_id"]) for event in asked] == [("state", 7)], "the dashboard's pending button waits on this"
        assert [event["event"] for event in events if event.get("req_id") == 7] == ["discovered"]
        assert not saves, "a command that changes nothing writes nothing"
        answered = await engine.request({"cmd": "discover"})
        assert [event["event"] for event in answered] == ["discovered", "state"]


async def test_plugins_read_as_disabled_while_the_hub_runs_none() -> None:
    platform = FakePlatform()
    platform.plugin_runtime = None
    engine = Engine(platform)
    await engine.start()
    await install_demo(engine)
    assert engine.plugins.get("demo").enabled
    assert not engine.state_event()["plugins"][0]["enabled"], "the dashboard would keep running a plugin the hub has switched off"
    platform.plugin_runtime = object()
    assert engine.state_event()["plugins"][0]["enabled"]


async def test_a_plugin_the_hub_runs_none_of_is_answered_on_nothing_it_asks_for() -> None:
    platform = FakePlatform()
    platform.responses["https://hooks.example.com/x"] = (200, {"ok": 1})
    engine = Engine(platform)
    await engine.start()
    manifest = {**MANIFEST, "permissions": ["net", "notify", "link:provide"], "reasons": dict.fromkeys(["net", "notify", "link:provide"], "to test"), "provides": {"feed": "a feed"}}
    await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest)})
    await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": manifest["permissions"], "enabled": True}})
    platform.plugin_runtime = None
    platform.http_calls.clear()

    for command in (
        {"cmd": "plugin.http", "id": "demo", "url": "https://hooks.example.com/x"},
        {"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "t", "url": "wss://hooks.example.com/x"},
        {"cmd": "plugin.effect", "id": "demo", "effect": {"kind": "notify", "text": "hi"}},
        {"cmd": "plugin.publish", "id": "demo", "channel": "feed", "body": {}},
    ):
        with pytest.raises(RuntimeError, match="may not|not answering|is answering"):
            await engine.request(command)

    assert not platform.http_calls and not platform.sockets, "an installed plugin still reached the network with plugins off"
    await engine.stop()


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
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Detecting serial connection"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.2}})
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


@pytest.mark.parametrize("completion", [float("nan"), float("inf"), 1e999])
async def test_a_printer_reading_that_is_not_finite_is_an_unreadable_printer(completion: float) -> None:
    """One such number in the state would end every dashboard's socket, which cannot encode it."""
    from printguard.server.events import encode_event

    platform = FakePlatform()
    platform.responses["http://op/api/job"] = (200, {"state": "Printing", "progress": {"completion": completion}, "job": {"file": {"name": "a.gcode"}}})
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.3)
        assert engine.printers.get(printer_id).device_state["status"] == "offline"
        encode_event(engine.state_event())
        assert not [event for event in _of(events, "device") if event["status"] == "printing"]


async def test_a_saved_camera_that_cannot_open_says_why_until_it_does(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "REATTACH_EVERY_TICKS", 1)
    platform = FakePlatform()
    platform.state = {"cameras": [{**_FAKE_CAMERA, "source": {"kind": "url", "url": "rtsp://user:hunter2secret@cam/live"}}]}
    opening = platform.open_camera
    refusals = ["no decoder for this stream, user:hunter2secret", "this camera's last capture stopped answering. Restart PrintGuard to free it"]

    async def refuse(camera_id: str, source: dict) -> object:
        if refusals:
            raise RuntimeError(refusals.pop(0))
        return await opening(camera_id, source)

    monkeypatch.setattr(platform, "open_camera", refuse)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await asyncio.sleep(0.1)
        shown = engine.state_event()["cameras"][0]
        assert shown["online"] is False and shown["reason"].startswith("no decoder for this stream")
        assert "hunter2secret" not in shown["reason"]
        await asyncio.sleep(1.3)
        assert engine.state_event()["cameras"][0]["reason"].endswith("Restart PrintGuard to free it")
        await asyncio.sleep(1.2)
        shown = engine.state_event()["cameras"][0]
        assert (shown["online"], shown["reason"]) == (True, None)
        assert "reason" not in engine.cameras.values()[0].persisted()


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

    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.1)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "ACT_RETRY_S", 0.01)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 0.3)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    monkeypatch.setattr(engine_module, "REATTACH_EVERY_TICKS", 1)
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.reject_actions = True
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 0.2}}
        )
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
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 0.05)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, events):
        camera = next(iter(engine.cameras.values()))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.05}})
        await asyncio.sleep(0.1)
        stalled_source = camera.frame_source
        stalled_source.frozen = True
        for _ in range(150):
            if any(event.get("event") == "warning" and event["recovered"] for event in events):
                break
            await asyncio.sleep(0.02)

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


async def test_a_stall_is_announced_through_the_watchdogs_own_restarts(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    scale = 0.01
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", watchdog.WATCH_TICK_S * scale)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", watchdog.STALL_GRACE_S * scale)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", watchdog.RESTART_AFTER_S * scale)
    monkeypatch.setattr(watchdog, "RESTART_COOLDOWN_S", watchdog.RESTART_COOLDOWN_S * scale)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", watchdog.RECOVER_HOLD_S * scale)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", watchdog.GRACE_MIN_S * scale)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.01)
    open_camera = platform.open_camera
    frozen = False

    async def open_as_it_stands(camera_id: str, source: dict):
        await asyncio.sleep(watchdog.WATCH_TICK_S * 2)
        opened = await open_camera(camera_id, source)
        opened.frozen = frozen
        return opened

    monkeypatch.setattr(platform, "open_camera", open_as_it_stands)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, events):
        camera = next(iter(engine.cameras.values()))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": watchdog.GRACE_DEFAULT_S * scale}})
        await asyncio.sleep(0.1)
        frozen = True
        camera.frame_source.frozen = True
        await asyncio.sleep((watchdog.STALL_GRACE_S + watchdog.GRACE_DEFAULT_S * scale) * 2)

        def warnings(recovered: bool) -> list[dict]:
            return [e for e in events if e.get("event") == "warning" and e["recovered"] is recovered]

        assert len(platform.released_cameras) >= 2, "the stalled camera was not attached afresh more than once"
        assert [w["message"] for w in warnings(False)] == [
            f"Camera '{camera.name}' feed has stalled, so 'm-{camera.name}' is NOT being monitored"
        ], "a stall the restarts did not cure was not announced once"
        assert not warnings(True), "a restart that produced no inference was announced as a recovery"

        frozen = False
        for _ in range(300):
            if warnings(True):
                break
            await asyncio.sleep(0.02)
        assert [w["message"] for w in warnings(True)] == [
            f"Camera '{camera.name}' feed recovered, so 'm-{camera.name}' is monitored again"
        ]
        assert any(e.get("event") == "result" for e in events[events.index(warnings(False)[0]) : events.index(warnings(True)[0])])


async def test_a_feed_that_gives_a_frame_each_time_it_is_attached_is_called_unreliable(monkeypatch) -> None:
    """Each re-attach brings an inference, so no stall ever lasts the grace period, yet the print is mostly unwatched."""
    scale = 0.02
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", watchdog.WATCH_TICK_S * scale)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", watchdog.STALL_GRACE_S * scale)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", watchdog.RESTART_AFTER_S * scale)
    monkeypatch.setattr(watchdog, "RESTART_COOLDOWN_S", watchdog.RESTART_COOLDOWN_S * scale)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", watchdog.GRACE_MIN_S * scale)
    monkeypatch.setattr(watchdog, "COVERAGE_SAMPLES", 100)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.04)
    platform = FakePlatform(infer_s=0.01)
    open_camera = platform.open_camera

    async def open_then_freeze(camera_id: str, source: dict):
        opened = await open_camera(camera_id, source)
        asyncio.get_running_loop().call_later(0.2, setattr, opened, "frozen", True)
        return opened

    monkeypatch.setattr(platform, "open_camera", open_then_freeze)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": watchdog.GRACE_DEFAULT_S * scale}})
        await asyncio.sleep(8.0)

    warned = [event["message"] for event in _of(events, "warning") if not event["recovered"]]
    assert len(platform.released_cameras) >= 3, "the feed was not attached afresh each time it froze"
    assert len(warned) == 1 and "is not being monitored reliably" in warned[0], f"a feed frozen most of the time warned {warned}"


async def test_a_feed_that_stalls_and_then_drops_is_announced_as_one_fault(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", 0.1)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 10.0)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, events):
        camera = next(iter(engine.cameras.values()))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.5}})
        await asyncio.sleep(0.1)
        camera.frame_source.frozen = True
        await asyncio.sleep(0.3)
        camera.frame_source.online = False
        await asyncio.sleep(1.2)

    warned = [event["message"] for event in _of(events, "warning")]
    assert warned == [f"Camera '{camera.name}' is offline, so 'm-{camera.name}' is NOT being monitored"], f"one dead camera warned {warned}"


async def _one_slow_printer(platform: FakePlatform, monkeypatch, slow_host: str) -> tuple[asyncio.Event, asyncio.Event]:
    """Has the printer at one address hold its answer until released.

    Returns:
        An event set once the slow printer is being read, and the event that lets it answer.
    """
    answer = platform.http
    reading = asyncio.Event()
    release = asyncio.Event()
    release.set()

    async def slow(method: str, url: str, **request) -> tuple[int, object]:
        if slow_host in url:
            reading.set()
            await release.wait()
        return await answer(method, url, **request)

    monkeypatch.setattr(platform, "http", slow)
    return reading, release


async def _add_printers(engine: Engine, *hosts: str) -> None:
    for host in hosts:
        await engine.handle(
            {"cmd": "printer.add", "printer": {"name": host, "provider": "octoprint", "config": {"base_url": f"http://{host}", "api_key": "k"}}}
        )


async def test_a_printer_that_does_not_answer_holds_up_nobody_elses_poll(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform()
    _, release = await _one_slow_printer(platform, monkeypatch, "slow.lan")
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await _add_printers(engine, "slow.lan", "quick.lan")
        await asyncio.sleep(0.05)
        quick = engine.printers.values()[1]
        platform.device_status = "Paused"
        release.clear()
        poll = asyncio.create_task(engine.watchdog.poll_devices())
        for _ in range(50):
            if quick.reported_status == "paused":
                break
            await asyncio.sleep(0.01)
        read_meanwhile = quick.reported_status
        release.set()
        await poll

    assert read_meanwhile == "paused", "a printer waited on one that was not answering"


async def test_a_printer_that_does_not_answer_does_not_stretch_the_poll_of_the_others(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.1)
    platform = FakePlatform()
    answer = platform.http
    live_reads = 0

    async def http(method: str, url: str, **request: Any) -> tuple[int, Any]:
        nonlocal live_reads
        if "dead.lan" in url and url.endswith("/api/job"):
            await asyncio.sleep(1.5)
            raise OSError("timed out")
        if "live.lan" in url and url.endswith("/api/job"):
            live_reads += 1
        return await answer(method, url, **request)

    monkeypatch.setattr(platform, "http", http)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await _add_printers(engine, "live.lan", "dead.lan")
        live_reads = 0
        await asyncio.sleep(1.0)

    assert live_reads >= 5, f"a printer that never answered held every other printer's poll back: {live_reads} reads in 1 s"


async def test_a_printer_removed_while_it_answers_a_poll_is_not_reported(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform()
    reading, release = await _one_slow_printer(platform, monkeypatch, "gone.lan")
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await _add_printers(engine, "kept.lan", "gone.lan")
        await asyncio.sleep(0.05)
        removed_id = engine.printers.values()[1].id
        platform.device_status = "Paused"
        reading.clear()
        release.clear()
        events.clear()
        poll = asyncio.create_task(engine.watchdog.poll_devices())
        await asyncio.wait_for(reading.wait(), 1.0)
        await engine.handle({"cmd": "printer.remove", "id": removed_id})
        release.set()
        await poll

    assert [e["printer_id"] for e in _of(events, "device")] == [engine.printers.values()[0].id]


async def test_brief_outage_reattaches_without_notifying(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 0.05)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 1.0}}
        )
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        camera = next(iter(engine.cameras.values()))
        dropped_source = camera.frame_source
        dropped_source.online = False
        await asyncio.sleep(0.4)

        assert camera.frame_source is not dropped_source and camera.online, "a dropped camera waited on the grace period to recover"
        assert not [e for e in events if e.get("event") == "warning"], "an outage inside the grace period warned"
        assert not _pushes(platform), "an outage inside the grace period pushed a notification"


def _recording_notifier(real):
    class Recorder(type(real)):
        def __init__(self) -> None:
            self.sent: list[tuple[str, bool]] = []

        async def send(self, http, config, title, body, image, *, urgent: bool = True) -> None:
            self.sent.append((title, urgent))

    return Recorder()


async def test_a_recovery_is_sent_quietly_and_a_fault_or_defect_is_urgent(monkeypatch) -> None:
    from printguard.engine import engine as engine_module
    from printguard.engine.notifiers import NOTIFIERS

    notifier = _recording_notifier(NOTIFIERS["ntfy"])
    monkeypatch.setitem(NOTIFIERS, "ntfy", notifier)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 10.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.05)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 0.05}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True, "consecutive": 1}})
        camera = next(iter(engine.cameras.values()))
        source = camera.frame_source
        source.online = False
        await asyncio.sleep(0.4)
        source.online = True
        camera.frame_source = source
        for _ in range(100):
            if any(event.get("event") == "warning" and event["recovered"] for event in events):
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.1)

    by_title = {title: urgent for title, urgent in notifier.sent}
    assert by_title["PrintGuard warning"] is True, "a fault was sent quietly"
    assert by_title["PrintGuard recovered"] is False, "a recovery rang as urgent"
    assert any(title.startswith("PrintGuard: ") and urgent for title, urgent in notifier.sent), "a defect alert was not urgent"


async def test_an_alert_whose_picture_could_not_be_encoded_says_so(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)

    async def no_picture(rgb: np.ndarray) -> None:
        return None

    monkeypatch.setattr(platform, "encode_jpeg", no_picture)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True, "consecutive": 1}})
        await asyncio.sleep(1.0)

    assert _of(events, "alert"), "no alert was raised"
    warnings = [e["message"] for e in _of(events, "warning")]
    assert any("without a picture" in message for message in warnings), warnings


async def test_sustained_outage_keeps_reminding(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 10.0)
    monkeypatch.setattr(watchdog, "REPEAT_EVERY_S", 0.2)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 0.05}}
        )
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        camera = next(iter(engine.cameras.values()))
        camera.frame_source.online = False
        await asyncio.sleep(0.7)
        monkeypatch.setattr(watchdog, "REPEAT_EVERY_S", 3600.0)
        await asyncio.sleep(0.05)

        warnings = [e for e in events if e.get("event") == "warning" and "is offline" in e["message"]]
        assert len(warnings) >= 3, f"an outage nobody answered was announced {len(warnings)} times"
        assert len(_pushes(platform)) == len(warnings), "reminders were not pushed to the notifiers"


async def test_camera_that_keeps_dropping_warns_about_the_feed(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 10.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(watchdog, "COVERAGE_SAMPLES", 10)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 1.0}}
        )
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"notify": True}})
        camera = next(iter(engine.cameras.values()))

        for _ in range(6):
            camera.frame_source.online = False
            await asyncio.sleep(0.1)
            camera.frame_source.online = True
            await asyncio.sleep(0.05)

        unreliable = [e for e in events if e.get("event") == "warning" and "dropped out for" in e["message"]]
        assert len(unreliable) == 1, f"a camera that kept dropping warned {len(unreliable)} times"
        assert not [e for e in events if e.get("event") == "warning" and "is offline" in e["message"]], (
            "no single drop was long enough to be announced as an outage"
        )
        assert len(_pushes(platform)) == 1, f"an unreliable feed pushed {len(_pushes(platform))} notifications"

        await asyncio.sleep(0.4)
        recoveries = [e for e in events if e.get("event") == "warning" and e["recovered"]]
        assert any("steady again" in r["message"] for r in recoveries), "a feed that settled was never announced"


async def _unreliable_feed(engine: Engine, events: list[dict]):
    """Drops a camera in and out until its feed is warned about as unreliable, and returns it."""
    await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 0.5}})
    await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"notify": True}})
    camera = next(iter(engine.cameras.values()))
    for _ in range(6):
        camera.frame_source.online = False
        await asyncio.sleep(0.1)
        camera.frame_source.online = True
        await asyncio.sleep(0.05)
    assert [e for e in _of(events, "warning") if "dropped out for" in e["message"]], "the feed was never warned about"
    return camera


def _shrunk_coverage_window(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 10.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    monkeypatch.setattr(watchdog, "COVERAGE_SAMPLES", 10)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)


async def test_an_unreliable_feed_that_then_dies_is_never_called_steady(monkeypatch) -> None:
    _shrunk_coverage_window(monkeypatch)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        camera = await _unreliable_feed(engine, events)
        camera.frame_source.online = False
        await asyncio.sleep(1.2)

        assert [e for e in _of(events, "warning") if "is offline" in e["message"]], "the outage itself was never announced"
        assert not [e for e in _of(events, "warning") if e["recovered"]], "a camera that is offline was announced as recovered"
        assert len(_pushes(platform)) == 2, "the unreliable feed and then the outage are the only notices"

        camera.frame_source.online = True
        await asyncio.sleep(0.6)
        recoveries = [e["message"] for e in _of(events, "warning") if e["recovered"]]
        assert len(recoveries) == 1 and "is back" in recoveries[0], f"the outage's own recovery is the one notice, got {recoveries}"


async def test_an_unreliable_feed_is_forgotten_when_the_monitor_stands_down(monkeypatch) -> None:
    _shrunk_coverage_window(monkeypatch)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        camera = await _unreliable_feed(engine, events)
        camera.frame_source.online = False
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await asyncio.sleep(0.1)
        camera.frame_source.online = True
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
        await asyncio.sleep(0.5)

        assert not [e for e in _of(events, "warning") if e["recovered"]], "the next print opened with a recovery from the last one"


async def test_fault_grace_cannot_be_turned_off() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _events):
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0}})
        assert engine.settings["fault_grace_s"] == watchdog.GRACE_MIN_S, "an unwatched print must always be announced"
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 86400}})
        assert engine.settings["fault_grace_s"] == watchdog.GRACE_MAX_S, "the grace period must stay bounded"


async def test_flapping_camera_warns_once_per_outage(monkeypatch) -> None:
    from printguard.engine import engine as engine_module

    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.2)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle(
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}, "fault_grace_s": 0.05}}
        )
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
        assert len(_pushes(platform)) == 1, f"flapping pushed {len(_pushes(platform))} notifications"

        await hold_source(True, 0.5)
        assert len(warnings(True)) == 1, "sustained recovery was never announced"
        assert len(_pushes(platform)) == 2, "recovery should push exactly once"

        await hold_source(False, 0.15)
        await hold_source(True, 0.3)
        assert len(warnings(True)) == 1, "a camera that fails again must settle for longer before recovery is announced"
        await hold_source(True, 0.6)
        assert len(warnings(True)) == 2, "recovery was never announced after the longer settled period"


async def test_protocol_surfaces_errors_and_refuses_unknown_settings() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "nope", "req_id": 7})
        assert any(e["event"] == "error" and "unknown command" in e["message"] and e.get("req_id") == 7 for e in events)
        with pytest.raises(RuntimeError, match="unknown command"):
            await engine.request({"cmd": "nope"})

        await engine.handle({"cmd": "monitor.update", "id": "missing", "patch": {}, "req_id": 8})
        assert any(e["event"] == "error" and e.get("req_id") == 8 for e in events)

        assert engine.settings["theme"] == "system" and engine.settings["themes"] == [], "theme settings default"
        assert engine.settings["layout"] == {}, "layout settings default"

        custom = {"id": "t1", "name": "Mine", "base": "dark", "colors": {"accent": "#123456"}}
        layout = {
            "monitors": {"order": ["m2", "m1"], "pinned": ["m2"], "hidden": ["m3"]},
            "cameras": {"order": [], "pinned": [], "hidden": ["c1"]},
        }
        patch = {"notifiers": {"ntfy": {"url": "u"}}, "theme": "light", "themes": [custom], "layout": layout}
        await engine.handle({"cmd": "settings.update", "patch": {"bogus": 1, **patch}, "req_id": 9})
        assert any(e["event"] == "error" and e["message"] == "there is no bogus setting" and e.get("req_id") == 9 for e in events)
        assert "bogus" not in engine.settings and engine.settings["theme"] == "system", "a patch with an unknown setting changes nothing"
        await engine.handle({"cmd": "settings.update", "patch": patch})
        assert engine.settings["notifiers"] == {"ntfy": {"url": "u"}}
        assert engine.settings["theme"] == "light"
        assert engine.settings["themes"] == [custom]
        assert engine.settings["layout"] == layout

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.settings["layout"] == layout, "layout settings survive a restart"


async def test_an_mqtt_port_stored_as_text_by_an_older_version_holds_up_no_other_setting() -> None:
    platform = FakePlatform()
    platform.state = {"settings": {"mqtt": {"host": "broker", "port": "1883"}}}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.request({"cmd": "settings.update", "patch": {"theme": "dark"}})
        assert engine.settings["theme"] == "dark"
        with pytest.raises(RuntimeError, match="MQTT port"):
            await engine.request({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "port": "1883"}}})


async def test_a_setting_changed_during_a_runtime_switch_is_kept(monkeypatch) -> None:
    platform = FakePlatform()
    configure = platform.configure

    async def slow_configure(settings: dict) -> None:
        await asyncio.sleep(0.2)
        await configure(settings)

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        monkeypatch.setattr(platform, "configure", slow_configure)
        switch = asyncio.ensure_future(engine.handle({"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}}))
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "settings.update", "patch": {"theme": "dark"}})
        await switch
        assert (engine.settings["theme"], engine.settings["inference_runtime"]) == ("dark", "onnx")
        assert platform.state["settings"]["theme"] == "dark" and platform.inference_runtime == "onnx"


async def test_a_runtime_switch_cancelled_while_the_model_loads_still_finishes(monkeypatch) -> None:
    platform = FakePlatform()
    configure = platform.configure

    async def slow_configure(settings: dict) -> None:
        await asyncio.sleep(0.2)
        await configure(settings)

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        monkeypatch.setattr(platform, "configure", slow_configure)
        await _cancelled_after(engine, {"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}}, 0.05)
        await asyncio.sleep(0.5)
        assert platform.inference_runtime == "onnx", "the load was cut short"
        assert engine.settings["inference_runtime"] == "onnx", "the setting names a runtime that is not the one loaded"
        assert platform.state["settings"]["inference_runtime"] == "onnx", "state.json still names the old runtime"


UNRENDERABLE = {
    "a layout whose order is not a list": {"layout": {"monitors": {"order": "m1"}}},
    "a layout section that is not an object": {"layout": {"cameras": ["c1"]}},
    "a layout that is not an object": {"layout": "compact"},
    "a custom theme with no base or colours": {"themes": [{"id": "t1", "name": "Mine"}]},
    "a custom theme with no name": {"themes": [{"id": "t1", "base": "dark", "colors": {}}]},
    "a colour that is not a colour": {"themes": [{"id": "t1", "name": "Mine", "base": "dark", "colors": {"accent": 7}}]},
    "a colour by name": {"themes": [{"id": "t1", "name": "Mine", "base": "dark", "colors": {"accent": "red"}}]},
    "themes that are not a list": {"themes": {"t1": {}}},
    "a theme that is not a name": {"theme": ["light"]},
    "glass that is not an object": {"glass": 0.5},
    "a glass opacity that is not a number": {"glass": {"opacity": "NaN", "tone": 0}},
}


@pytest.mark.parametrize("patch", UNRENDERABLE.values(), ids=UNRENDERABLE.keys())
async def test_a_theme_or_layout_no_dashboard_could_render_is_refused(patch: dict) -> None:
    """Every open dashboard renders what one caller saved, and throws on these."""
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": patch, "req_id": 4})

        assert any(e["event"] == "error" and e.get("req_id") == 4 for e in events)
        assert {key: engine.settings[key] for key in patch} == {key: engine_module.SETTINGS_DEFAULTS[key] for key in patch}


async def test_glass_is_held_between_clear_and_solid() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "settings.update", "patch": {"glass": {"opacity": 7, "tone": -1, "blur": 9}}})

        assert engine.settings["glass"] == {"opacity": 1.0, "tone": 0.0}


async def test_a_layout_stored_before_it_was_checked_no_longer_blanks_the_dashboard() -> None:
    platform = FakePlatform()
    platform.state = {"settings": {"layout": {"monitors": {"order": 5}}, "theme": "dark", "update_check": False}}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.settings["layout"] == {}
        assert engine.settings["update_check"] is False, "a setting that was fine was reset with it"


async def test_printer_heat_sets_each_target_then_refreshes_the_state() -> None:
    platform = FakePlatform()
    platform.responses["http://op/api/printer?exclude=sd,state"] = (
        200,
        {"temperature": {"tool0": {"actual": 24.6, "target": 0.0}, "bed": {"actual": 23.1, "target": 0.0}}},
    )
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "printer.heat", "id": printer_id, "nozzle": 215, "bed": 60, "req_id": 3})
        posted = [(r["url"], r["json"]) for r in platform.http_requests if r["method"] == "POST"]
        assert posted == [
            ("http://op/api/printer/tool", {"command": "target", "targets": {"tool0": 215.0}}),
            ("http://op/api/printer/bed", {"command": "target", "target": 60.0}),
        ]
        device = next(e for e in events if e.get("event") == "device")
        assert device["nozzle"] == {"actual": 24.6, "target": 0.0} and device["bed"] == {"actual": 23.1, "target": 0.0}
        assert engine.state_event()["printers"][0]["device_state"]["nozzle"] == {"actual": 24.6, "target": 0.0}

        await engine.handle({"cmd": "printer.heat", "id": printer_id, "req_id": 5})
        assert any(e.get("event") == "error" and e.get("req_id") == 5 for e in events), "naming no heater is refused"


@pytest.mark.parametrize(
    ("fields", "named"),
    [
        ({"nozzle": 400}, "nozzle"),
        ({"nozzle": 351}, "nozzle"),
        ({"bed": 150.5}, "bed"),
        ({"bed": 2100}, "bed"),
        ({"nozzle": -1}, "nozzle"),
        ({"nozzle": "210"}, "nozzle"),
        ({"bed": True}, "bed"),
        ({"bed": False}, "bed"),
        ({"nozzle": 210, "bed": 400}, "bed"),
    ],
)
async def test_a_heater_target_out_of_range_or_not_a_number_is_refused_and_sends_nothing(fields: dict, named: str) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "printer.heat", "id": printer_id, "req_id": 4, **fields})
        error = next(e for e in events if e.get("event") == "error" and e.get("req_id") == 4)
        assert error["message"].startswith(f"{named} temperature must be a number"), error
        assert not [r for r in platform.http_requests if r["method"] == "POST"], "a heater was sent a target that was refused"


async def test_the_hottest_and_coolest_heater_targets_are_still_taken() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "printer.heat", "id": printer_id, "nozzle": 350, "bed": 0, "req_id": 4})
        assert not [e for e in events if e.get("event") == "error"]
        assert len([r for r in platform.http_requests if r["method"] == "POST"]) == 2


async def test_preheat_presets_default_and_are_sanitised() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.state_event()["settings"]["preheat"] == PREHEAT_DEFAULTS
        await engine.handle(
            {
                "cmd": "settings.update",
                "patch": {"preheat": [{"name": "  Nylon  6 ", "nozzle": 999, "bed": -5}, {"name": "", "nozzle": 200, "bed": 60}]},
            }
        )
        assert engine.settings["preheat"] == [{"name": "Nylon 6", "nozzle": 350.0, "bed": 0.0}]
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.settings["preheat"] == [{"name": "Nylon 6", "nozzle": 350.0, "bed": 0.0}], "presets survive a restart"


@pytest.mark.parametrize("unbounded", [float("nan"), float("inf")])
async def test_a_number_that_is_not_finite_is_refused_by_name(unbounded: float) -> None:
    """NaN compares false with both bounds, so a bare max and min hand back the top of the range."""
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[5.0]) as (engine, events):
        printer_id = await _register_printer(engine)
        camera = next(iter(engine.cameras.values()))
        (monitor_id,) = engine.monitors
        before = (dict(engine.monitors[monitor_id]), camera.brightness, camera.crop, engine.settings["preheat"])
        refused = {
            "nozzle temperature": {"cmd": "printer.heat", "id": printer_id, "nozzle": unbounded},
            "bed temperature": {"cmd": "settings.update", "patch": {"preheat": [{"name": "PLA", "nozzle": 210, "bed": unbounded}]}},
            "threshold": {"cmd": "monitor.update", "id": monitor_id, "patch": {"threshold": unbounded}},
            "cooldown_s": {"cmd": "monitor.update", "id": monitor_id, "patch": {"cooldown_s": unbounded}},
            "brightness": {"cmd": "camera.update", "id": camera.id, "patch": {"brightness": unbounded}},
            "detect_fps": {"cmd": "camera.update", "id": camera.id, "patch": {"detect_fps": unbounded}},
            "crop w": {"cmd": "camera.update", "id": camera.id, "patch": {"crop": {"x": 0.1, "y": 0.1, "w": unbounded, "h": 0.5}}},
        }
        for req_id, (field, command) in enumerate(refused.items()):
            await engine.handle({**command, "req_id": req_id})
            error = next(e for e in events if e.get("event") == "error" and e.get("req_id") == req_id)
            assert error["message"].startswith(f"{field} must be a finite number"), error
        assert not [r for r in platform.http_requests if r["method"] == "POST"], "a heater was sent a target that is not a number"
        assert before == (engine.monitors[monitor_id], camera.brightness, camera.crop, engine.settings["preheat"])


@pytest.mark.parametrize(
    "crop",
    [{"x": 1.0, "y": 0.0, "w": 0.5, "h": 1.0}, {"x": 0.0, "y": 1.0, "w": 1.0, "h": 0.5}, {"x": 0.7, "y": 0.7, "w": 0.9, "h": 0.9}],
)
async def test_a_crop_is_kept_inside_the_frame(crop: dict) -> None:
    async with running_engine(FakePlatform(), camera_fps=[5.0]) as (engine, _):
        camera = next(iter(engine.cameras.values()))
        await engine.request({"cmd": "camera.update", "id": camera.id, "patch": {"crop": crop}})
        assert camera.crop["x"] + camera.crop["w"] <= 1.0 and camera.crop["y"] + camera.crop["h"] <= 1.0, camera.crop


class _SlowCameraPlatform(FakePlatform):
    release_s = 0.0
    open_s = 0.0

    async def release_camera(self, camera_id: str, source: dict) -> None:
        await asyncio.sleep(self.release_s)
        await super().release_camera(camera_id, source)

    async def open_camera(self, camera_id: str, source: dict):
        await asyncio.sleep(self.open_s)
        return await super().open_camera(camera_id, source)


def _webcam(url: str, key: str = "webcam"):
    async def cameras(http, config):
        return [{"key": key, "name": "cam", "source": {"kind": "url", "url": url}}]

    return cameras


async def test_a_poll_of_the_old_service_answering_during_a_provider_change_is_not_kept(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    old_answer = asyncio.Event()

    async def old_state(http, config):
        await old_answer.wait()
        return DeviceState(DeviceStatus.IDLE)

    async def new_state(http, config):
        raise RuntimeError("new service is unreachable")

    async def no_cameras(http, config):
        return []

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "fetch_state", old_state)
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", _webcam("http://old/stream"))
    monkeypatch.setattr(INTEGRATIONS["klipper"], "fetch_state", new_state)
    monkeypatch.setattr(INTEGRATIONS["klipper"], "cameras", no_cameras)
    platform = _SlowCameraPlatform()
    platform.release_s = 0.3
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)
        assert engine.cameras.values(), "the old service's camera was not registered"
        printer = engine.printers.get(printer_id)
        poll = asyncio.create_task(engine.watchdog.refresh(printer))
        await asyncio.sleep(0.05)
        edit = asyncio.create_task(
            engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://new"}}})
        )
        await asyncio.sleep(0.1)
        old_answer.set()
        await asyncio.gather(poll, edit)

    assert printer.reported_status is None and printer.device_state is None, "the old service's answer stuck on the printer's new one"


async def test_a_camera_listed_from_the_old_service_is_not_registered_after_a_provider_change(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", _webcam("http://old/stream"))
    monkeypatch.setattr(INTEGRATIONS["klipper"], "cameras", _webcam("http://new/stream", "abc123"))
    platform = _SlowCameraPlatform()
    platform.open_s = 0.3
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://new"}}})
        await asyncio.sleep(1.0)
        urls = [camera.source["url"] for camera in engine.cameras.values()]

    assert urls == ["http://new/stream"], urls


async def test_a_reconcile_queued_behind_another_does_not_reach_a_printer_removed_meanwhile(monkeypatch) -> None:
    calls: list[str] = []

    async def cameras(http, config):
        calls.append("cameras")
        return [{"key": "webcam", "name": "cam", "source": {"kind": "url", "url": "http://old/stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", cameras)
    platform = _SlowCameraPlatform()
    platform.open_s = 0.3
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "renamed"}})
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "printer.remove", "id": printer_id})
        await asyncio.sleep(0.8)

    assert calls == ["cameras"], "a printer that was removed had its service asked for cameras again"
    assert not engine.cameras.values()


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


async def test_a_readdressed_printer_forgets_the_status_read_at_its_old_address(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    answer = platform.http

    async def only_the_old_address_answers(method: str, url: str, **kwargs):
        if url.startswith("http://typo"):
            raise OSError("no route to host")
        return await answer(method, url, **kwargs)

    monkeypatch.setattr(platform, "http", only_the_old_address_answers)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.2)
        assert not engine.state_event()["monitors"][0]["watching"], "an idle printer stands its monitor down"
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://typo", "api_key": "k"}}})
        await asyncio.sleep(0.2)
        assert engine.state_event()["monitors"][0]["watching"], "idle was read from an address the printer no longer has"


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


async def test_declared_camera_registers_is_managed_and_follows_the_deployment() -> None:
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "/dev/nozzle-cam", "label": "HD Pro Webcam C920", "declared": True}]
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)

    camera = engine.cameras.values()[0]
    assert camera.declared and camera.name == "HD Pro Webcam C920", "the declared device was not registered at boot"
    assert camera.source == {"kind": "device", "device_id": "/dev/nozzle-cam", "label": "HD Pro Webcam C920"}

    await engine.handle({"cmd": "camera.remove", "id": camera.id, "req_id": 7})
    assert engine.cameras.get(camera.id) is not None, "a declared camera cannot be removed on its own"
    assert any(e["event"] == "error" and e.get("req_id") == 7 for e in events)

    await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"name": "Nozzle"}})
    await engine.stop()

    restarted = Engine(platform)
    await restarted.start()
    assert [(c.id, c.name) for c in restarted.cameras.values()] == [(camera.id, "Nozzle")], "the camera was not restored to its name"
    await restarted.stop()

    platform.devices = [{**platform.devices[0], "declared": False}]
    undeclared = Engine(platform)
    await undeclared.start()
    assert not undeclared.cameras.values(), "the camera stayed registered after the deployment stopped declaring it"
    await undeclared.stop()


async def test_a_declared_camera_missing_at_boot_stays_offline_and_comes_back_as_it_was(monkeypatch) -> None:
    """A device unplugged for one boot must not cost the camera its name and tuning."""
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    device = {"kind": "device", "device_id": "/dev/nozzle-cam", "label": "HD Pro Webcam C920", "declared": True}
    tuning = {"name": "Nozzle", "rotation": 180, "brightness": 1.4, "detect_fps": 2.0}
    platform = FakePlatform(infer_s=0.02)
    platform.devices = [device]
    engine = Engine(platform)
    await engine.start()
    camera_id = engine.cameras.values()[0].id
    await engine.handle({"cmd": "camera.update", "id": camera_id, "patch": tuning})
    tuned = {key: engine.state_event()["cameras"][0][key] for key in tuning}
    await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.1}})
    await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": camera_id}})
    await engine.stop()
    assert tuned == tuning

    platform.devices = []
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)
    await asyncio.sleep(0.5)
    missing = engine.state_event()["cameras"]
    await engine.stop()
    assert [(c["id"], c["online"]) for c in missing] == [(camera_id, False)], "a camera missing at boot was not kept, offline"
    assert any("'Nozzle' is offline" in event["message"] for event in _of(events, "warning")), "nobody was told the monitor is unwatched"

    platform.devices = [device]
    engine = Engine(platform)
    events = []
    await engine.start()
    engine.add_sink(events.append)
    await asyncio.sleep(0.5)
    returned = engine.state_event()
    await engine.handle({"cmd": "camera.remove", "id": camera_id, "req_id": 3})
    await engine.stop()
    assert {key: returned["cameras"][0][key] for key in tuning} == tuning, "the camera came back without its name and tuning"
    assert returned["cameras"][0]["declared"] and returned["monitors"][0]["watching"] and _of(events, "result")
    assert any(e.get("req_id") == 3 for e in _of(events, "error")), "a camera the deployment passes in was removed on its own"

    platform.devices = []
    engine = Engine(platform)
    await engine.start()
    await engine.handle({"cmd": "camera.remove", "id": camera_id})
    gone = engine.state_event()
    await engine.stop()
    assert gone["cameras"] == [] and gone["monitors"][0]["camera_id"] == "", "a camera that is gone for good could not be removed"


async def test_discovery_hides_registered_devices() -> None:
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "Cam", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "discover", "req_id": 1})
        assert next(e for e in events if e["event"] == "discovered")["sources"] == platform.devices

        await engine.handle({"cmd": "camera.add", "name": "Cam", "source": {"kind": "device", "device_id": "/dev/video0"}})
        await engine.handle({"cmd": "discover", "req_id": 2})
        assert next(e for e in events if e.get("req_id") == 2 and e["event"] == "discovered")["sources"] == []


async def test_discovery_does_not_offer_the_hubs_own_camera_streams(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "cam", "source": {"kind": "url", "url": "http://op/stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await _register_printer(engine)
        await asyncio.sleep(0.1)
        own = [camera.id for camera in engine.cameras.values()]
        assert len(own) == 2 and any(camera_id.endswith("-webcam") for camera_id in own)
        platform.devices = [{"kind": "path", "path": camera_id, "label": camera_id} for camera_id in own]
        platform.devices.append({"kind": "path", "path": "someone-elses", "label": "someone-elses"})
        await engine.handle({"cmd": "discover", "req_id": 2})
        listed = next(e for e in events if e.get("req_id") == 2 and e["event"] == "discovered")["sources"]

    assert [source["path"] for source in listed] == ["someone-elses"]


async def test_discovery_hides_a_device_registered_under_the_name_it_shows() -> None:
    """A Windows camera added before 2.6.0 is stored by its name, and is now listed by its device path."""
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "HD Pro Webcam C920", "label": "HD Pro Webcam C920", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.add", "name": "Cam", "source": {"kind": "device", "device_id": "HD Pro Webcam C920"}})
        platform.devices = [{"kind": "device", "device_id": "@device_pnp_usb#vid_046d", "label": "HD Pro Webcam C920", "declared": False}]
        await engine.handle({"cmd": "discover", "req_id": 2})
        assert next(e for e in events if e.get("req_id") == 2 and e["event"] == "discovered")["sources"] == []


async def test_discovery_hides_only_the_first_of_two_same_model_cameras_when_one_was_added_by_name() -> None:
    """On 2.5.0 the second one could not be added at all, and the first was opened by the name they share."""
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "HD Pro Webcam C920", "label": "HD Pro Webcam C920", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.add", "name": "Cam", "source": {"kind": "device", "device_id": "HD Pro Webcam C920"}})
        platform.devices = [
            {"kind": "device", "device_id": "@device_pnp_usb#6", "label": "HD Pro Webcam C920 (1)", "declared": False},
            {"kind": "device", "device_id": "@device_pnp_usb#7", "label": "HD Pro Webcam C920 (2)", "declared": False},
        ]
        await engine.handle({"cmd": "discover", "req_id": 2})
        listed = next(e for e in events if e.get("req_id") == 2 and e["event"] == "discovered")["sources"]

    assert [source["device_id"] for source in listed] == ["@device_pnp_usb#7"]


async def test_what_the_platform_worked_around_is_raised_as_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """An accelerator passed over for the CPU, or a live view that cannot publish, was only a log line."""
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[15]) as (engine, events):
        camera_id = next(iter(engine.cameras.items))
        platform.notices += [
            Notice("Intel GPU cannot run the model, so detection is not using it: out of memory"),
            Notice("live view unavailable: connection refused", camera_id=camera_id),
            Notice("live view restored", recovered=True, camera_id=camera_id),
        ]
        await asyncio.sleep(0.1)
        name = engine.cameras.get(camera_id).name
        assert [(e["message"], e["recovered"]) for e in events if e["event"] == "warning"] == [
            ("Intel GPU cannot run the model, so detection is not using it: out of memory", False),
            (f"'{name}' live view unavailable: connection refused", False),
            (f"'{name}' live view restored", True),
        ]
        assert platform.notices == []


async def test_camera_add_refuses_a_source_already_registered() -> None:
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "Cam", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        for req_id, source in enumerate(
            [
                {"kind": "device", "device_id": "/dev/video0"},
                {"kind": "device", "device_id": "/dev/video0", "label": "Cam"},
                {"kind": "url", "url": "rtsp://cam.local/stream"},
                {"kind": "url", "url": "rtsp://cam.local/stream"},
            ]
        ):
            await engine.handle({"cmd": "camera.add", "name": "Cam", "source": source, "req_id": req_id})
        assert [camera.source.get("device_id") or camera.source["url"] for camera in engine.cameras.values()] == [
            "/dev/video0",
            "rtsp://cam.local/stream",
        ]
        refused = [event for event in events if event["event"] == "error"]
        assert [event["req_id"] for event in refused] == [1, 3]
        assert "already registered" in refused[0]["message"]


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "device", "device_id": "/dev/video0", "url": None},
        {"kind": "url", "url": 5},
        {"kind": "url", "url": ["rtsp://cam.local/stream"]},
        {"kind": "device", "device_id": {"path": "/dev/video0"}},
        {"kind": "path", "path": 7},
        {"kind": 3, "url": "rtsp://cam.local/stream"},
        "rtsp://cam.local/stream",
    ],
)
async def test_camera_add_refuses_a_source_the_next_start_could_not_read(source) -> None:
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "Cam", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        with pytest.raises(RuntimeError, match="a camera's source"):
            await engine.request({"cmd": "camera.add", "name": "Cam", "source": source})
        assert engine.cameras.values() == []

    restarted = Engine(platform)
    await restarted.start()
    try:
        assert restarted.startup_warnings == []
    finally:
        await restarted.stop()


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


def test_preprocess_averages_sensor_noise_on_a_still_scene() -> None:
    assets = vision.Assets(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225), prototypes={})
    scene = np.full((720, 1280, 3), 128.0)
    noisy = np.clip(scene + np.random.default_rng(0).normal(0, 8, scene.shape), 0, 255).astype(np.uint8)

    residual = vision.preprocess(noisy, assets) - vision.preprocess(scene.astype(np.uint8), assets)

    assert residual.std() < 0.04, "point sampling leaves about 0.09 of noise for the model to score"
    assert vision.preprocess(vision.transform(noisy, rotation=90), assets).shape == (1, 3, 224, 224)


def test_a_score_that_is_not_a_number_never_leaves_the_model() -> None:
    assert vision.defect_score({"distances": {"success": float("inf"), "failure": float("inf")}}) == 0.5


async def test_camera_rotation_persists_and_rejects_off_axis() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"rotation": 90}})
        assert camera.rotation == 90
        assert camera.public()["rotation"] == 90
        with pytest.raises(RuntimeError, match="rotation is 0, 90, 180 or 270"):
            await engine.request({"cmd": "camera.update", "id": camera.id, "patch": {"rotation": 45}})
        assert camera.rotation == 90, "an off-axis rotation is refused"
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


def test_watch_time_is_the_time_readings_spanned_and_not_the_minutes_they_touched() -> None:
    from printguard.engine.history import MonitorHistory

    brief = MonitorHistory()
    for second in range(50, 65):
        brief.record(float(second), 0.1, 0.75)
    assert brief.series([])["stats"]["watch_min"] == 0, "15 seconds of watching straddling a minute read as 2 minutes"

    long = MonitorHistory()
    for second in range(0, 301):
        long.record(float(second), 0.1, 0.75)
    assert long.series([])["stats"]["watch_min"] == 5

    paused = MonitorHistory()
    for second in (*range(0, 61), *range(3600, 3661)):
        paused.record(float(second), 0.1, 0.75)
    stats = paused.series([])["stats"]
    assert stats["watch_min"] == 2 and isinstance(stats["watch_min"], int), "the hour the monitor stood down counted as watched"


def test_a_gap_between_readings_is_split_across_the_buckets_it_spans() -> None:
    from printguard.engine.history import MonitorHistory

    history = MonitorHistory()
    for second in (50.0, 70.0, 90.0, 110.0, 130.0, 150.0, 170.0):
        history.record(second, 0.1, 0.75)
    buckets = history.series([])["buckets"]

    assert [bucket["watched"] for bucket in buckets] == [10.0, 60.0, 50.0]
    assert history.series([])["stats"]["watch_min"] == 2


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


async def test_an_inference_cancelled_before_it_starts_frees_its_worker_and_camera() -> None:
    platform = FakePlatform(infer_s=0.01)
    engine = Engine(platform)
    await engine.start()
    try:
        for task in engine._tasks:
            task.cancel()
        await asyncio.gather(*engine._tasks, return_exceptions=True)
        await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 15}})
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "monitor.add", "monitor": {"camera_id": camera.id}})
        await asyncio.sleep(0.2)
        results: list[int] = []
        original = engine.scheduler._on_result

        async def spy(camera, frame, result):
            results.append(frame.seq)
            await original(camera, frame, result)

        engine.scheduler._on_result = spy

        await engine.scheduler.dispatch()
        assert camera.inferring
        await engine.restart_camera(camera)
        await asyncio.sleep(0.05)
        assert not camera.inferring, "a job cancelled before its first step left the camera inferring for good"

        await asyncio.sleep(0.3)
        await asyncio.wait_for(engine.scheduler.dispatch(), 2.0)
        await asyncio.sleep(0.2)
        assert results, "the only worker was still taken by the cancelled job"
    finally:
        await engine.stop()


async def test_a_runtime_switch_behind_a_wedged_inference_gives_up_and_says_so(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "RUNTIME_DRAIN_TIMEOUT_S", 0.1)
    platform = FakePlatform(infer_s=0.01)
    platform.inference_blocked = True
    async with running_engine(platform, camera_fps=[30.0]) as (engine, _):
        await asyncio.wait_for(platform.inference_started.wait(), timeout=1.0)
        platform.inference_blocked = False
        with pytest.raises(RuntimeError, match="the runtime was not switched"):
            await engine.request({"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}}, timeout=1.0)
        assert (engine.settings["inference_runtime"], platform.inference_runtime) == ("auto", "auto")
        await engine.request({"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}}, timeout=1.0)
        assert platform.inference_runtime == "onnx", "the next switch is not held up by the one that gave up"


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
        assert engine.state_event()["reviews"] == [] and not platform.files.blobs, "a removed monitor's kept frames are deleted"


async def _review(engine: Engine, review_id: str) -> dict:
    return next(e for e in await engine.request({"cmd": "review.get", "id": review_id}) if e["event"] == "review")


async def test_alert_snapshots_survive_a_restart() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(1.0)

    restarted = Engine(platform)
    await restarted.start()
    try:
        history = next(e for e in await restarted.request({"cmd": "history.get", "monitor_id": monitor_id}) if e["event"] == "history")
        snapshot = next(e for e in await restarted.request({"cmd": "snapshot.get", "monitor_id": monitor_id, "id": history["snaps"][0]["id"]}) if e["event"] == "snapshot")
    finally:
        await restarted.stop()
    assert len(history["snaps"]) == 1 and history["stats"]["snaps"] == 1, "the alert's frame was lost with the restart"
    assert base64.b64decode(snapshot["jpeg"]) == b"\xff\xd8fake", "the kept frame's bytes did not come back from the file store"


async def test_a_print_keeps_a_thinned_spread_of_frames_and_its_near_misses(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.01)
    monkeypatch.setattr(reviews, "NEAR_APART_S", 0.3)
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, _):
        await asyncio.sleep(2.0)
        summary = engine.state_event()["reviews"][0]
        review = await _review(engine, summary["id"])

    frames = review["frames"]
    spaced = [frame for frame in frames if frame["kind"] == "spaced"]
    near = [frame for frame in frames if frame["kind"] == "near"]
    assert summary["ended"] is None and summary["frames"] > 0 and "spacing_s" not in summary, "the state carries a running print's summary"
    assert 3 <= len(spaced) < reviews.SPACED_MAX, "the spread is thinned once it reaches its cap"
    gaps = [later["ts"] - earlier["ts"] for earlier, later in zip(spaced[:-2], spaced[1:-1])]
    assert min(gaps) > 0.05, "thinning should have widened the gap between spaced frames"
    assert 1 <= len(near) <= reviews.NEAR_MAX and all(frame["score"] < 0.5 for frame in near), "near misses score under the threshold"
    assert not [frame for frame in frames if frame["kind"] == "alert"], "a clean print has no alert frames"
    assert len(platform.files.blobs) == len(frames), "every kept frame has its JPEG stored, and thinned ones are deleted"


async def test_a_review_ends_when_the_printer_goes_idle_and_not_on_a_pause(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(0.4)
        platform.device_status = "Paused"
        await asyncio.sleep(0.4)
        paused = [review["ended"] for review in engine.state_event()["reviews"]]
        platform.device_status = "Printing"
        await asyncio.sleep(0.4)
        platform.device_status = "Operational"
        await asyncio.sleep(0.4)
        finished = [review["ended"] for review in engine.state_event()["reviews"]]
        platform.device_status = "Printing"
        await asyncio.sleep(0.4)
        again = [review["ended"] for review in engine.state_event()["reviews"]]
        persisted = platform.state["reviews"]

    assert paused == [None], "a pause is part of the same print"
    assert len(finished) == 1 and finished[0] is not None, "an idle printer ends the print's review"
    assert len(again) == 2 and again[1] is None, "the next print opens a review of its own"
    assert persisted[0]["ended"] == finished[0], "a finished review is persisted"


async def test_the_oldest_finished_reviews_make_room_for_new_prints(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "REVIEW_MAX", 2)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        seen: list[str] = []
        for _ in range(3):
            await asyncio.sleep(0.3)
            seen.append(engine.state_event()["reviews"][-1]["id"])
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
        await asyncio.sleep(0.3)
        kept = engine.state_event()["reviews"]
        frames = sum(review["frames"] for review in kept)

    assert len(set(seen)) == 3, "switching a monitor off ends its print"
    assert len(kept) == 2 and seen[0] not in [review["id"] for review in kept], "the oldest finished review is dropped first"
    assert len(platform.files.blobs) == frames, "a dropped review's frames are deleted with it"


async def test_prints_still_running_do_not_push_out_finished_ones(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "REVIEW_MAX", 2)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0, 10.0, 10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(0.4)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
        await asyncio.sleep(0.4)
        kept = engine.state_event()["reviews"]

    assert [review["status"] for review in kept].count("running") == 3
    assert [review["status"] for review in kept].count("ready") == 1, "three running prints left no room for the one that finished"


async def test_two_prints_beginning_at_the_cap_do_not_evict_the_same_review(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "REVIEW_MAX", 1)
    platform = FakePlatform()
    library = reviews.ReviewLibrary(platform)
    frame = Frame(rgb=np.zeros((48, 64, 3), dtype=np.uint8), seq=1.0, ts=0.0)
    first, second = ({"id": name, "threshold": 0.75, "printer_id": "", "enabled": False} for name in ("first", "second"))
    for monitor in (first, second):
        await library.sample(monitor, frame, 0.1, 0.0)
    library.settle({"first": first, "second": second}, {}, set(), True)

    kept = await asyncio.gather(library.sample(first, frame, 0.1, 10.0), library.sample(second, frame, 0.1, 10.0), return_exceptions=True)

    assert kept == [True, True], "one of the two prints lost its frame"
    running = [review["frames"] for review in library.public() if review["status"] == "running"]
    assert running == [1, 1], "each new print keeps its first frame"
    assert len(platform.files.blobs) == sum(review["frames"] for review in library.public()), "an evicted review's frame was left behind"


async def test_a_print_beginning_while_the_review_is_switched_off_keeps_no_frame(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "REVIEW_MAX", 1)
    platform = FakePlatform()
    library = reviews.ReviewLibrary(platform)
    frame = Frame(rgb=np.zeros((48, 64, 3), dtype=np.uint8), seq=1.0, ts=0.0)
    monitor = {"id": "m", "threshold": 0.75, "printer_id": "", "enabled": False}
    await library.sample(monitor, frame, 0.1, 0.0)
    library.settle({"m": monitor}, {}, set(), True)
    remove = platform.files.remove
    evicting = asyncio.Event()

    async def slow_remove(key: str) -> None:
        evicting.set()
        await asyncio.sleep(0.1)
        await remove(key)

    monkeypatch.setattr(platform.files, "remove", slow_remove)
    sampling = asyncio.create_task(library.sample(monitor, frame, 0.1, 100.0))
    await evicting.wait()
    await library.stop_asking()
    await sampling

    assert [review["frames"] for review in library.public()] == [0], "a frame was kept after the review was switched off"
    assert not platform.files.blobs, "the frame's file stayed on disk"


async def test_a_print_with_no_frames_kept_does_not_wait_for_a_review(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    monkeypatch.setattr(platform.files, "store", _disk_full)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await asyncio.sleep(0.4)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"enabled": False}})
        ended = engine.state_event()["reviews"]

    assert [(review["frames"], review["status"]) for review in ended] == [(0, "dismissed")], "a print with nothing kept prompted for a review"


TOKEN = f"{'a' * 32}.{'b' * 64}"


def _inbox(platform: FakePlatform, monkeypatch, refuse=lambda uploads: None) -> list[dict]:
    """Stands in for the feedback Worker, refusing an upload whenever ``refuse`` returns an answer."""
    uploads: list[dict] = []
    passthrough = platform.http

    async def http(method: str, url: str, **request) -> tuple[int, object]:
        if url == f"{feedback.ENDPOINT}/register":
            assert request.get("json") == {}, "the Worker refuses a registration that is not JSON, which a web page cannot send cross-site"
            platform.http_calls.append((method, url))
            return 201, {"token": TOKEN}
        if url == f"{feedback.ENDPOINT}/frame":
            answer = refuse(uploads)
            if answer is not None:
                return answer
            uploads.append({"authorization": request["headers"]["Authorization"], "jpeg": request["data"], **json.loads(request["headers"]["X-Frame"])})
            return 201, {}
        return await passthrough(method, url, **request)

    monkeypatch.setattr(platform, "http", http)
    return uploads


def _slow_inbox(platform: FakePlatform, monkeypatch) -> list[dict]:
    """An inbox that takes 100 ms over each frame, so a test can act while a print uploads."""
    uploads = _inbox(platform, monkeypatch)
    inbox = platform.http

    async def slow_inbox(method: str, url: str, **request) -> tuple[int, object]:
        if url == f"{feedback.ENDPOINT}/frame":
            await asyncio.sleep(0.1)
        return await inbox(method, url, **request)

    monkeypatch.setattr(platform, "http", slow_inbox)
    return uploads


async def _finished_review(engine: Engine, wait_s: float = 1.0) -> dict:
    """Lets a print run, ends it by switching its monitor off and on, and returns its frames."""
    monitor_id = next(iter(engine.monitors))
    await asyncio.sleep(wait_s)
    await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
    return await _review(engine, engine.state_event()["reviews"][0]["id"])


async def _sent(events: list[dict]) -> dict:
    for _ in range(100):
        outcome = next((event for event in reversed(events) if event.get("event") == "review_sent"), None)
        if outcome:
            return outcome
        await asyncio.sleep(0.02)
    raise AssertionError("the review was never sent")


async def test_a_reviewed_print_is_sent_with_its_labels(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    uploads = _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        alert = next(frame for frame in review["frames"] if frame["kind"] == "alert")
        spaced = [frame for frame in review["frames"] if frame["kind"] == "spaced"]
        assert review["status"] == "ready" and len(spaced) >= 2
        await engine.handle({"cmd": "review.send", "id": review["id"], "failures": [alert["id"]], "removed": [spaced[0]["id"]], "printer": "  Voron   2.4 "})
        outcome = await _sent(events)
        state = engine.state_event()

    by_frame = {upload["frame"]: upload for upload in uploads}
    assert outcome["ok"] and outcome["status"] == "sent" and outcome["sent"] == outcome["chosen"] == len(review["frames"]) - 1
    assert set(by_frame) == {frame["id"] for frame in review["frames"]} - {spaced[0]["id"]}, "a removed frame is never uploaded"
    assert by_frame[alert["id"]]["label"] == "failure" and by_frame[spaced[1]["id"]]["label"] == "good"
    sent = by_frame[alert["id"]]
    assert sent["authorization"] == f"Bearer {TOKEN}" and sent["jpeg"] == b"\xff\xd8fake"
    assert (sent["print"], sent["kind"], sent["printer"], sent["provider"], sent["version"]) == (review["id"], "alert", "Voron 2.4", "none", platform.version)
    assert sent["threshold"] == 0.75 and sent["score"] == alert["score"] and sent["ts"] == alert["ts"]
    assert state["feedback_hub"] == "a" * 32 and TOKEN not in json.dumps(state), "the state names the hub and never carries its token"
    assert platform.state["feedback_token"] == TOKEN, "the token is kept so the hub registers once"
    assert platform.http_calls.count(("POST", f"{feedback.ENDPOINT}/register")) == 1


def test_a_typed_printer_model_is_cut_to_what_the_inbox_takes() -> None:
    assert feedback.printer_model(None) == ""
    assert feedback.printer_model("  Voron \n 2.4\t") == "Voron 2.4"
    assert feedback.printer_model("Ender\x1b[2J\x00 3\x7f") == "Ender[2J 3"
    assert feedback.printer_model("Prusa \u00e9\u4e2d") == "Prusa \u00e9\u4e2d"
    assert len(feedback.printer_model("a" * 200)) == feedback.PRINTER_MODEL_MAX


async def test_a_refused_print_waits_and_sends_the_rest_after_the_limit_resets(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    limited = {"until": float("inf")}

    def refuse(uploads: list[dict]):
        if len(uploads) >= 2 and time.time() < limited["until"]:
            return 429, {"code": "hub_daily", "retry_at": limited["until"]}

    uploads = _inbox(platform, monkeypatch, refuse)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        limited["until"] = time.time() + 0.4
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        refused = await _sent(events)
        queued = engine.state_event()["reviews"][0]
        events.clear()
        resumed = await _sent(events)

    assert not refused["ok"] and (refused["status"], refused["code"], refused["sent"]) == ("queued", "hub_daily", 2)
    assert queued["retry_at"] == limited["until"], "the hub is told when the limit resets"
    assert resumed["ok"] and resumed["sent"] == resumed["chosen"] == len(review["frames"]) and resumed["code"] is None
    assert sorted(upload["frame"] for upload in uploads) == sorted(frame["id"] for frame in review["frames"]), "no frame is uploaded twice"


async def test_a_print_dismissed_before_its_upload_begins_sends_nothing_and_leaves_no_send_behind(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    uploads = _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        await asyncio.gather(
            engine.handle({"cmd": "review.send", "id": review["id"]}),
            engine.handle({"cmd": "review.dismiss", "id": review["id"]}),
        )
        await asyncio.sleep(0.2)
        status = engine.state_event()["reviews"][0]["status"]

    assert not uploads and status == "dismissed"
    assert not engine._sends, "a send that stopped before it began was never cleared"
    assert not _of(events, "error")


async def test_a_print_queued_to_send_is_never_pushed_out_by_newer_ones(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "REVIEW_MAX", 2)
    platform = FakePlatform(infer_s=0.02)
    _inbox(platform, monkeypatch, lambda uploads: (429, {"code": "hub_daily", "retry_at": time.time() + 3600}))
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(0.3)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        queued_id = engine.state_event()["reviews"][0]["id"]
        await engine.handle({"cmd": "review.send", "id": queued_id})
        await _sent(events)
        for _ in range(3):
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
            await asyncio.sleep(0.3)
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        kept = {review["id"]: review["status"] for review in engine.state_event()["reviews"]}

    assert kept[queued_id] == "queued", "a print waiting for the inbox was deleted with its frames, unsent"
    assert any(f"review-{queued_id}-" in key for key in platform.files.blobs)
    assert len(kept) == 2, "the other prints still make room for each other"


@pytest.mark.parametrize("command", ["review.send", "review.retry"])
async def test_a_print_is_not_sent_while_the_review_switch_is_off(monkeypatch, command: str) -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    uploads = _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        review = await _finished_review(engine)
        with pytest.raises(RuntimeError, match="switched off"):
            await engine.request({"cmd": command, "id": review["id"]})
        await asyncio.sleep(0.2)

    assert not uploads and ("POST", f"{feedback.ENDPOINT}/register") not in platform.http_calls, "frames reached the inbox with feedback off"


async def test_a_second_send_during_an_upload_is_answered_by_that_upload(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    uploads = _slow_inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        frames = [frame["id"] for frame in review["frames"]]
        await engine.handle({"cmd": "review.send", "id": review["id"], "req_id": "first"})
        await asyncio.sleep(0.15)
        await engine.handle({"cmd": "review.send", "id": review["id"], "failures": frames, "req_id": "second"})
        await asyncio.sleep(0.2 * len(frames) + 0.5)
        state = engine.state_event()

    answers = {event["req_id"]: (event["ok"], event["sent"]) for event in _of(events, "review_sent") if event.get("req_id")}
    assert answers == {"first": (True, len(frames)), "second": (True, len(frames))}, "the second request was not answered by the upload in flight"
    assert sorted(upload["frame"] for upload in uploads) == sorted(frames), "a frame was uploaded twice"
    assert not _of(events, "error") and state["reviews"][0]["status"] == "sent"


async def test_a_print_whose_monitor_is_gone_is_dropped_with_a_message_and_not_left_sending(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02, failing=True)
    uploads = _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        engine.monitors.clear()
        await asyncio.sleep(0.3)
        listed = engine.state_event()["reviews"]

    assert not uploads and not listed, "frames of a monitor that no longer exists were kept or sent"
    assert not engine._sends
    assert any("monitor was removed" in e["message"] for e in _of(events, "error")), _of(events, "error")


async def test_a_reset_time_already_past_on_the_hubs_clock_does_not_retry_every_tick(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    attempts: list[float] = []

    def refuse(uploads: list[dict]):
        attempts.append(time.time())
        return 429, {"code": "global_daily", "retry_at": time.time() - 30.0}

    _inbox(platform, monkeypatch, refuse)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine, 0.4)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.5)
        queued = engine.state_event()["reviews"][0]

    assert len(attempts) == 1, f"a hub whose clock is ahead of the inbox's asked {len(attempts)} times in half a second"
    assert queued["code"] == "global_daily"
    assert time.time() + engine_module.FEEDBACK_RECHECK_S - 5 < queued["retry_at"] < time.time() + engine_module.FEEDBACK_RECHECK_S + 5, "a reset time already past was put off for hours"


async def test_an_unreachable_inbox_keeps_the_frames_and_tries_again_later(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    reachable = platform.http

    async def unreachable(method: str, url: str, **request) -> tuple[int, object]:
        raise OSError("no route")

    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine, 0.4)
        monkeypatch.setattr(platform, "http", unreachable)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        outcome = await _sent(events)
        stored = len(platform.files.blobs)
        monkeypatch.setattr(platform, "http", reachable)
        _inbox(platform, monkeypatch)
        events.clear()
        await engine.handle({"cmd": "review.retry", "id": review["id"]})
        retried = await _sent(events)

    assert not outcome["ok"] and (outcome["status"], outcome["code"], outcome["sent"]) == ("queued", "offline", 0)
    assert outcome["retry_at"] > time.time() + engine_module.FEEDBACK_RETRY_S - 60
    assert stored == len(review["frames"]), "nothing is lost when the inbox cannot be reached"
    assert retried["ok"] and retried["sent"] == len(review["frames"]), "a queued print can be sent again by hand"


async def test_a_send_cut_short_by_a_restart_is_picked_up_again(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    reachable = platform.http

    async def hanging(method: str, url: str, **request) -> tuple[int, object]:
        if url.startswith(feedback.ENDPOINT):
            await asyncio.Event().wait()
        return await reachable(method, url, **request)

    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        review = await _finished_review(engine, 0.4)
        monkeypatch.setattr(platform, "http", hanging)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.05)

    monkeypatch.setattr(platform, "http", reachable)
    uploads = _inbox(platform, monkeypatch)
    restarted = Engine(platform)
    events: list[dict] = []
    await restarted.start()
    restarted.add_sink(events.append)
    try:
        outcome = await _sent(events)
    finally:
        await restarted.stop()
    assert outcome["ok"] and len(uploads) == len(review["frames"]), "a print left part way through sending is sent after the restart"


async def test_a_frame_that_can_never_be_sent_does_not_hold_up_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02)
    rejected: list[bool] = []

    def refuse(uploads: list[dict]):
        if not rejected:
            rejected.append(True)
            return 400, {"code": "details"}

    uploads = _inbox(platform, monkeypatch, refuse)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        assert len(review["frames"]) >= 3
        del platform.files.blobs[reviews.frame_key(review["id"], review["frames"][-1]["id"])]
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        outcome = await _sent(events)

    assert outcome["ok"] and outcome["status"] == "sent", "one rejected frame and one missing file do not queue the print for good"
    assert len(uploads) == len(review["frames"]) - 2
    assert outcome["sent"] == outcome["chosen"] == len(uploads), "a frame the inbox never took is not counted as sent"


async def test_an_unrecognised_token_is_replaced_once(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.state = {"feedback_token": "stale"}
    answered = {"stale": False}

    def refuse(uploads: list[dict]):
        if not answered["stale"]:
            answered["stale"] = True
            return 401, {"code": "token"}

    uploads = _inbox(platform, monkeypatch, refuse)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine, 0.4)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        outcome = await _sent(events)

    assert outcome["ok"] and len(uploads) == len(review["frames"])
    assert platform.state["feedback_token"] == TOKEN and {upload["authorization"] for upload in uploads} == {f"Bearer {TOKEN}"}


async def test_a_print_is_reviewed_once_and_only_after_it_ends(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await asyncio.sleep(0.4)
        running = engine.state_event()["reviews"][0]
        await engine.handle({"cmd": "review.send", "id": running["id"], "req_id": 1})
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await engine.handle({"cmd": "review.dismiss", "id": running["id"]})
        dismissed = engine.state_event()["reviews"][0]["status"]
        frames = (await _review(engine, running["id"]))["frames"]
        await engine.handle({"cmd": "review.send", "id": running["id"], "removed": [frame["id"] for frame in frames], "req_id": 2})
        await engine.handle({"cmd": "review.send", "id": running["id"]})
        await _sent(events)
        await engine.handle({"cmd": "review.send", "id": running["id"], "req_id": 3})

    errors = {event.get("req_id") for event in events if event["event"] == "error"}
    assert running["status"] == "running" and dismissed == "dismissed", "a dismissed print keeps its frames and can still be sent"
    assert errors == {1, 2, 3}, "a running print, an empty selection and a second send are all refused"


async def test_switching_feedback_off_keeps_only_alert_frames_and_asks_nothing() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "sometimes"}, "req_id": 9})
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        review = await _finished_review(engine)

    assert any(event["event"] == "error" and event.get("req_id") == 9 for event in events), "an unknown feedback setting is refused"
    assert {frame["kind"] for frame in review["frames"]} == {"alert"}, "the risk history still gets its alert snapshots"
    assert review["status"] == "dismissed", "a finished print does not wait for a review nobody asked for"


async def test_switching_feedback_off_holds_when_a_kept_frame_cannot_be_deleted(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    remove = platform.files.remove
    stuck: list[str] = []

    async def remove_unless_stuck(key: str) -> None:
        if not stuck:
            stuck.append(key)
        if key == stuck[0]:
            raise PermissionError(f"cannot delete {key}")
        await remove(key)

    async with running_engine(platform, camera_fps=[10.0, 10.0]) as (engine, events):
        await asyncio.sleep(0.5)
        for monitor_id in list(engine.monitors):
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        monkeypatch.setattr(platform.files, "remove", remove_unless_stuck)
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}, "req_id": "off"})
        state = next(event for event in reversed(events) if event.get("event") == "state" and event.get("req_id") == "off")
        saved = platform.state["settings"]["feedback"]
        statuses = [review["status"] for review in engine.state_event()["reviews"]]

    assert not [event for event in _of(events, "error") if event.get("req_id") == "off"], "the switch was refused although it took effect"
    assert state["settings"]["feedback"] == saved == "off", "the switch took effect in memory but was never saved or announced"
    assert statuses == ["dismissed", "dismissed"]
    assert [event["message"] for event in _of(events, "warning")] == [f"Could not delete the frames kept for review: cannot delete {stuck[0]}"]
    assert list(platform.files.blobs) == [stuck[0]], "one frame that cannot go left the others behind"


async def test_switching_feedback_off_settles_the_prints_that_already_ended(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    limited = {"until": float("inf")}

    def refuse(uploads: list[dict]):
        if len(uploads) >= 1 and time.time() < limited["until"]:
            return 429, {"code": "hub_daily", "retry_at": limited["until"]}

    uploads = _inbox(platform, monkeypatch, refuse)
    async with running_engine(platform, camera_fps=[10.0, 10.0]) as (engine, events):
        await asyncio.sleep(0.4)
        platform.failing = True
        await asyncio.sleep(0.5)
        for monitor_id in list(engine.monitors):
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        waiting, reviewed = engine.state_event()["reviews"]
        limited["until"] = time.time() + 0.3
        await engine.handle({"cmd": "review.send", "id": reviewed["id"]})
        await _sent(events)
        before = [review["status"] for review in engine.state_event()["reviews"]]

        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        after = [await _review(engine, review["id"]) for review in (waiting, reviewed)]
        await asyncio.sleep(0.6)

    assert before == ["ready", "queued"] and len(uploads) == 1
    assert [review["status"] for review in after] == ["dismissed", "dismissed"], "no print is left prompting or waiting to send"
    kept = [frame for review in after for frame in review["frames"]]
    assert kept and {frame["kind"] for frame in kept} == {"alert"}, "the risk history keeps its alert snapshots and nothing else stays"
    assert len(platform.files.blobs) == len(kept), "the dropped frames are deleted from disk"
    assert len(uploads) == 1, "a queued print was sent after the prompt was switched off"


async def test_switching_feedback_off_stops_a_print_that_is_uploading(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    uploads = _slow_inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.15)
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        outcome = await _sent(events)
        await asyncio.sleep(0.3)

    assert len(review["frames"]) >= 4
    assert len(uploads) == 2, f"only the frame in flight should finish, but {len(uploads)} of {len(review['frames'])} went"
    assert not outcome["ok"] and outcome["status"] == "dismissed"


async def test_cancelling_a_send_stops_after_the_frame_in_flight(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    uploads = _slow_inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.15)
        await engine.handle({"cmd": "review.dismiss", "id": review["id"]})
        outcome = await _sent(events)
        await asyncio.sleep(0.3)
        cancelled = engine.state_event()["reviews"][0]

    assert len(review["frames"]) >= 4
    assert len(uploads) == 2, f"only the frame in flight should finish, but {len(uploads)} of {len(review['frames'])} went"
    assert not outcome["ok"] and cancelled["status"] == "dismissed" and cancelled["chosen"] == 0, "a cancelled print ended up sent"


async def test_a_second_send_during_an_upload_replaces_the_choices_and_repeats_no_frame(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    uploads = _slow_inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        ids = [frame["id"] for frame in review["frames"]]
        await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.15)
        await engine.handle({"cmd": "review.send", "id": review["id"], "failures": ids[:1], "removed": ids[3:]})
        await asyncio.sleep(1.0)
        final = engine.state_event()["reviews"][0]

    assert len(ids) >= 5 and not _of(events, "error")
    assert {upload["frame"] for upload in uploads} == set(ids[:3]), "a frame the second send left out was uploaded anyway"
    assert [upload["frame"] for upload in uploads[:2]] == ids[:2], "the first send stops after the frame in flight"
    assert [upload["frame"] for upload in uploads[2:]] == [ids[2]], "a frame that was already sent went again"
    assert (final["status"], final["sent"], final["chosen"]) == ("sent", 3, 3)


async def test_the_clock_does_not_ask_again_for_a_print_that_is_uploading(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.02)
    platform = FakePlatform(infer_s=0.02)
    _slow_inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine)
        await engine.handle({"cmd": "review.send", "id": review["id"], "req_id": 7})
        await asyncio.sleep(0.2)
        assert engine._send_requests[review["id"]] == [7], "every tick queued another answer for the upload in flight"


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
        bystander: list[dict] = []
        engine.add_sink(bystander.append)
        requester: list[dict] = []
        await engine.handle({"cmd": "token.create", "req_id": 7, "name": "ci", "scope": "control"}, requester.append)

    assert not any(e.get("event") == "token_created" for e in events + bystander), "token secret reached a transport that did not ask"
    created = next(e for e in requester if e.get("event") == "token_created")
    assert created["req_id"] == 7 and created["scope"] == "control"
    assert engine.tokens.get(created["id"]) is not None, "token was not registered"
    secret = created["token"]
    assert secret.startswith("pg_"), "requester did not receive the one-time secret"
    assert all(secret not in line for line in logs.recent()), "token secret leaked into the log tail"


async def test_a_secret_any_module_logs_is_scrubbed_from_the_log() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with configured_logging(), running_engine(platform, camera_fps=[]) as (engine, _):
        keyed = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "octo-secret"}}
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **keyed}})
        try:
            raise ConnectionError("no answer from http://op/api/job?apikey=octo-secret")
        except ConnectionError as exc:
            logging.getLogger("printguard.engine.integrations").warning("camera listing failed: %s", exc, exc_info=True)

    assert any("camera listing failed: no answer from http://op/api/job?apikey=[redacted]" in line for line in logs.recent())
    assert all("octo-secret" not in line for line in logs.recent()), "the key reached the log"


def test_a_log_call_that_cannot_be_formatted_does_not_raise_in_its_caller(monkeypatch) -> None:
    monkeypatch.setattr(logging, "raiseExceptions", False)
    tail = logs.TailHandler()
    tail.handle(logging.LogRecord("library", logging.WARNING, __file__, 1, "%d frames", ("many",), None))
    assert not tail.lines


async def test_a_secret_an_error_quotes_reaches_no_transport_and_no_log(monkeypatch) -> None:
    """httpx refuses a header value that ends in a newline by quoting all of it."""
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http

    async def refuse(method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        if method == "POST":
            raise ValueError(f"Illegal header value {kwargs['headers']['X-Api-Key'].encode()!r}")
        return await answer(method, url, **kwargs)

    async with configured_logging(), running_engine(platform, camera_fps=[]) as (engine, events):
        pasted = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "octo-secret\n"}}
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **pasted}})
        monkeypatch.setattr(platform, "http", refuse)
        await engine.handle({"cmd": "printer.action", "id": next(iter(engine.printers.items)), "action": "pause", "req_id": 9})
        failed = next(e for e in _of(events, "error") if e.get("req_id") == 9)
        told = json.dumps([e for e in events if e["event"] != "state"] + engine.recent_events())

    assert failed["message"] == "Illegal header value b'[redacted]\\n'"
    assert "octo-secret" not in told, "the key reached a dashboard, a plugin or the events endpoint"
    assert all("octo-secret" not in line for line in logs.recent()), "the key reached the log"


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
    await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"granted": accepted}})
    await engine.handle({"cmd": "plugin.update", "id": "demo", "patch": {"enabled": True}})
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


async def test_the_work_a_failed_plugin_starts_is_held_and_ended_with_the_engine(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_demo(engine)
        stalled = asyncio.Event()

        async def never_closes(plugin_id: str) -> None:
            await stalled.wait()

        monkeypatch.setattr(engine.sockets, "drop_for", never_closes)
        engine.plugin_failed("demo", "ran out of fuel")
        await asyncio.sleep(0)

    pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    assert pending == [], "a task the engine started outlived it"


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
    platform.responses = {
        "https://api.github.com/repos/someone/pack/commits/main": (200, {"sha": sha}),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/plugin.json": (200, MANIFEST),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/plugin.js": (200, PLUGIN_JS),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/worker.js": (404, ""),
        f"https://raw.githubusercontent.com/someone/pack/{sha}/kit/panel.html": (404, ""),
    }
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle(
            {"cmd": "plugin.install", "source": {"kind": "github", "repo": "someone/pack", "path": "kit", "ref": "main"}}
        )
        record = engine.plugins.get("demo")

    assert record.source["ref"] == sha, "a moving branch was stored instead of the commit it resolved to"
    assert record.source["branch"] == "main", "an update would not know which branch to follow"
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
    platform.responses = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        platform.responses = github_files("b" * 40, {**SECRET_MANIFEST, "version": "1.1.0"})
        await install_from_github(engine)
        updated = engine.plugins.get("vault")

    assert updated.manifest["version"] == "1.1.0", "the new revision did not replace the old one"
    assert updated.source["branch"] == "main"
    assert updated.secrets["api_key"] == "s3cr3t", "an update made the user type its credentials again"
    assert updated.enabled and updated.granted == SECRET_MANIFEST["permissions"]


async def test_an_update_that_reaches_further_stands_the_plugin_down() -> None:
    """A wider manifest is a fresh question, the way a browser asks one again."""
    platform = FakePlatform(infer_s=0.02)
    platform.responses = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        wider = {**SECRET_MANIFEST, "urls": [*SECRET_MANIFEST["urls"], "https://collector.example.com/*"]}
        platform.responses = github_files("b" * 40, wider)
        await install_from_github(engine)
        updated = engine.plugins.get("vault")

    assert updated.granted == [], "an address nobody accepted was reached under the old consent"
    assert not updated.enabled, "a plugin that widened its reach kept running"
    assert updated.secrets["api_key"] == "s3cr3t", "the same plugin's own credentials were thrown away"


async def test_a_reinstalled_repository_whose_address_changed_only_in_case_keeps_running() -> None:
    """2.5.0 stored every pattern lowercased, and the reinstall that fixes a capital in a path must not cost the user their consent."""
    platform = FakePlatform(infer_s=0.02)
    spelt = {**SECRET_MANIFEST, "urls": ["https://api.example.com/bot*/sendMessage"]}
    platform.responses = github_files("a" * 40, spelt)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        saved = engine.plugins.get("vault")
        saved.manifest = {**saved.manifest, "urls": [url.lower() for url in saved.manifest["urls"]]}
        await install_from_github(engine)
        reinstalled = engine.plugins.get("vault")

    assert reinstalled.enabled and reinstalled.granted == SECRET_MANIFEST["permissions"], "a pattern spelt with a capital switched the plugin off"


async def test_a_zip_reinstalled_over_itself_keeps_its_stored_data_and_credentials() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file", "filename": "vault.zip"}, "zip": plugin_zip(SECRET_MANIFEST)})
        await engine.handle({"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "config": {"chat": "42"}}})
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file", "filename": "vault.zip"}, "zip": plugin_zip(SECRET_MANIFEST)})
        kept = engine.plugins.get("vault")
        wider = {**SECRET_MANIFEST, "urls": [*SECRET_MANIFEST["urls"], "https://collector.example.com/*"]}
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file", "filename": "vault.zip"}, "zip": plugin_zip(wider)})
        widened = engine.plugins.get("vault")

    assert kept.secrets["api_key"] == "s3cr3t" and kept.config == {"chat": "42"}, "a reinstall threw away what the user had typed"
    assert kept.granted == [], "a zip has no identity, so its permissions are asked again"
    assert widened.secrets == {} and widened.config == {}, "a zip that reached further inherited what an earlier one was given"


@pytest.mark.parametrize("endpoint", ["authorize_url", "token_url"])
async def test_an_update_that_signs_in_somewhere_else_is_signed_out_and_asked_again(endpoint: str) -> None:
    """A refresh token goes to the token endpoint, so a new one must not inherit it."""
    platform = FakePlatform(infer_s=0.02)
    platform.responses = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        engine.plugins.get("vault").secrets = {
            "api_key": "s3cr3t", "oauth_client_id": "mine-1234", "oauth": "at-1", "oauth_refresh": "rt-1", "oauth_expires": "0",
        }
        moved = {**SECRET_MANIFEST, "oauth": {**SECRET_MANIFEST["oauth"], endpoint: "https://collector.example.com/token"}}
        platform.responses = github_files("b" * 40, moved)
        await install_from_github(engine)
        updated = engine.plugins.get("vault")

    assert updated.secrets == {"api_key": "s3cr3t", "oauth_client_id": "mine-1234"}, "a session went to an endpoint that never issued it"
    assert updated.granted == [] and not updated.enabled, "a new sign-in address ran under the old consent"


async def test_a_bundle_from_somewhere_else_inherits_nothing_but_the_id() -> None:
    """An id is not an identity, so a stranger holding one starts with nothing."""
    platform = FakePlatform(infer_s=0.02)
    platform.responses = github_files("a" * 40, SECRET_MANIFEST)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle(
            {"cmd": "plugin.update", "id": "vault", "patch": {"granted": SECRET_MANIFEST["permissions"], "enabled": True}}
        )
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "s3cr3t"}})
        platform.responses = github_files("c" * 40, SECRET_MANIFEST, repo="squatter/pack")
        await install_from_github(engine, repo="squatter/pack")
        squatted = engine.plugins.get("vault")

    assert squatted.secrets == {}, "another author's bundle inherited the credentials"
    assert squatted.granted == [] and not squatted.enabled, "it ran on consent given to somebody else"


async def test_catalogue_verifies_only_the_exact_bytes_it_pinned() -> None:
    platform = FakePlatform(infer_s=0.02)
    digests = plugins.digests(plugins.sanitise_manifest(MANIFEST), {"plugin.js": PLUGIN_JS}, {})
    platform.responses = {plugins.CATALOGUE_URL: (200, {"plugins": [{"id": "demo", "name": "Demo", "digests": digests}]})}
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


async def test_the_oauth_permission_and_the_oauth_block_come_together() -> None:
    sign_in = SECRET_MANIFEST["oauth"]
    with pytest.raises(ValueError, match="go together"):
        plugins.sanitise_manifest({**SECRET_MANIFEST, "oauth": {}})
    with pytest.raises(ValueError, match="go together"):
        plugins.sanitise_manifest({**SECRET_MANIFEST, "oauth": sign_in, "permissions": ["net"], "reasons": {"net": "to post"}})


async def test_a_plugins_request_comes_back_tagged_as_it_named_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.responses["https://hooks.example.com/feed"] = (200, {"temp": 4})
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
    platform.responses["https://auth.example.com/token"] = (
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


async def test_a_secret_typed_while_a_sign_in_finishes_is_kept(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http

    async def slow_token(method: str, url: str, **kwargs):
        if url == "https://auth.example.com/token":
            await asyncio.sleep(0.2)
            return 200, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
        return await answer(method, url, **kwargs)

    monkeypatch.setattr(platform, "http", slow_token)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_vault(engine)
        await engine.handle({"cmd": "plugin.oauth", "id": "vault", "action": "start", "origin": "http://127.0.0.1:8000"})
        opened = next(e for e in events if e.get("event") == "plugin_oauth")["url"]
        finishing = asyncio.ensure_future(engine.finish_sign_in(parse_qs(urlparse(opened).query)["state"][0], "code-1"))
        await asyncio.sleep(0.05)
        await engine.handle({"cmd": "plugin.secrets", "id": "vault", "secrets": {"api_key": "typed-meanwhile"}})
        await finishing
        secrets = engine.plugins.get("vault").secrets

    assert (secrets["api_key"], secrets["oauth"]) == ("typed-meanwhile", "at-1")


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
    platform.responses["https://auth.example.com/token"] = (
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


async def test_a_refused_refresh_token_signs_the_plugin_out_once_and_the_provider_is_not_called_again() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.responses["https://auth.example.com/token"] = (400, {"error": "invalid_grant"})
    asked = {"cmd": "plugin.http", "id": "vault", "url": "https://api.example.com/v1/me", "headers": {"Authorization": "Bearer {{secret.oauth}}"}}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_vault(engine)
        plugin = engine.plugins.get("vault")
        plugin.secrets = {"oauth_client_id": "mine-1234", "oauth": "stale", "oauth_refresh": "rt-1", "oauth_expires": "0"}
        with pytest.raises(RuntimeError, match="signed out"):
            await engine.request(asked)
        with pytest.raises(RuntimeError, match="not signed in yet"):
            await engine.request(asked)
        refreshes = [url for method, url in platform.http_calls if url == "https://auth.example.com/token"]

    assert plugin.secrets == {"oauth_client_id": "mine-1234"}, "the panel would keep polling on a token nobody can renew"
    assert len(refreshes) == 1, "a refused refresh token was sent to the provider again"


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
        raw = next(e for e in await engine.request({"cmd": "history.get", "monitor_id": monitor_id}) if e["event"] == "history")

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
    assert plugins.project_event({"event": "alert", "monitor_id": "m1"}, ["state:read"]) is not None
    assert plugins.project_event({"event": "alert", "monitor_id": "m1"}, []) is None


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


def test_a_zip_declaring_more_than_a_plugin_may_ship_is_refused_before_it_is_unpacked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zeros deflate a thousandfold, so a small upload can name hundreds of megabytes of assets."""
    names = [f"a{index}.txt" for index in range(8)]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps({**MANIFEST, "assets": names, "media": names}))
        archive.writestr("plugin.js", PLUGIN_JS)
        for name in names:
            archive.writestr(name, bytes(plugins.MAX_ASSET_BYTES))
    unpacked: list[int] = []
    read = zipfile.ZipExtFile.read
    monkeypatch.setattr(zipfile.ZipExtFile, "read", lambda member, size=-1: unpacked.append(len(data := read(member, size))) or data)

    with pytest.raises(ValueError, match="a3.txt takes the plugin past"):
        plugins.unpack(buffer.getvalue())

    assert sum(unpacked) <= plugins.MAX_ASSETS_BYTES + 2 * plugins.MAX_SOURCE_BYTES, "assets were unpacked past the total before it was checked"


def test_a_zip_over_the_most_a_plugin_may_be_is_refused_before_it_is_opened() -> None:
    with pytest.raises(ValueError, match="over 12 MB"):
        plugins.unpack(bytes(plugins.MAX_ZIP_BYTES + 1))


def test_a_manifest_that_understates_its_size_is_not_inflated_whole() -> None:
    manifest = json.dumps(MANIFEST).encode()
    padded = manifest + b" " * (64 * 1024 * 1024)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("plugin.json", padded)
    raw = bytearray(buffer.getvalue())
    crc = zlib.crc32(manifest)
    struct.pack_into("<I", raw, 14, crc)
    struct.pack_into("<I", raw, 22, len(manifest))
    struct.pack_into("<I", raw, raw.rfind(b"PK\x01\x02") + 16, crc)
    struct.pack_into("<I", raw, raw.rfind(b"PK\x01\x02") + 24, len(manifest))
    tracemalloc.start()
    try:
        plugins.unpack(bytes(raw))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < 4 * 1024 * 1024, f"{peak // 1024 // 1024} MB was inflated for a manifest that declared {len(manifest)} bytes"


def test_a_zip_keeps_no_more_page_files_than_a_plugin_may_ship() -> None:
    shots = [f"media/shot{index}.png" for index in range(8)]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps({**MANIFEST, "media": shots}))
        for shot in shots:
            archive.writestr(shot, bytes(plugins.MAX_ASSET_BYTES))

    page = plugins.unpack(buffer.getvalue())[3]

    assert sum(len(data) for data in page.values()) == plugins.MAX_ASSETS_BYTES


async def test_a_repository_is_refused_at_the_asset_that_takes_it_past_the_total() -> None:
    platform = FakePlatform(infer_s=0.02)
    sha = "a" * 40
    names = [f"a{index}.txt" for index in range(8)]
    platform.responses = github_files(sha, {**MANIFEST, "assets": names}) | {
        f"https://raw.githubusercontent.com/someone/pack/{sha}/{name}": (200, base64.b64encode(bytes(plugins.MAX_ASSET_BYTES)).decode())
        for name in names
    }
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await install_from_github(engine)

    assert engine.plugins.get("demo") is None
    assert any(e.get("event") == "error" and "a3.txt takes the plugin past" in e["message"] for e in events)
    fetched = [request for request in platform.http_requests if request["url"].endswith(".txt")]
    assert [request["url"][-6:] for request in fetched] == ["a0.txt", "a1.txt", "a2.txt", "a3.txt"], "assets were still fetched past the total"
    assert all(request["max_bytes"] == plugins.MAX_ASSET_BYTES for request in fetched), "one download could be any size"


async def test_nothing_the_hub_fetches_for_itself_is_read_without_a_limit() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.responses = github_files("a" * 40, MANIFEST) | {plugins.CATALOGUE_URL: (200, {"plugins": []})}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_from_github(engine)
        await engine.handle({"cmd": "update.check"})

    asked = {urlparse(request["url"]).path.split("/")[-1]: request.get("max_bytes") for request in platform.http_requests}
    assert {"main", "catalogue.json", "releases"} <= set(asked), "the commit, the catalogue or the releases were never asked for"
    assert all(asked.values()), f"read to the end however long it ran: {[name for name, cap in asked.items() if not cap]}"


@pytest.mark.parametrize("asked,kept", [(300, 300.0), (4, 0.0), (10**9, 86400.0), ("Infinity", 0.0), ("NaN", 0.0), ("often", 0.0), ([60], 0.0)])
def test_a_manifest_keeps_a_timer_only_when_it_is_a_real_number_of_seconds(asked: object, kept: float) -> None:
    assert plugins.sanitise_manifest({**MANIFEST, "tick_s": asked})["tick_s"] == kept


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
    manifest = {**MANIFEST, "platforms": ["windows", "docker", "toaster"]}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest)})
        record = engine.plugins.get("demo").public()

    assert record["manifest"]["platforms"] == ["docker", "windows"]


async def test_a_plugin_for_another_platform_is_refused_from_any_source() -> None:
    platform = FakePlatform(infer_s=0.02)
    manifest = {**MANIFEST, "platforms": ["windows"]}
    platform.responses = github_files("a" * 40, manifest)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        with pytest.raises(RuntimeError, match="only runs on windows"):
            await engine.request({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip(manifest)})
        with pytest.raises(RuntimeError, match="only runs on windows"):
            await engine.request({"cmd": "plugin.install", "source": {"kind": "github", "repo": "someone/pack", "ref": "main"}})
        assert engine.plugins.get("demo") is None


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


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": "plugin.remove", "id": "demo"},
        {"cmd": "plugin.update", "id": "demo", "patch": {"enabled": False}},
        {"cmd": "plugin.secrets", "id": "demo", "secrets": {}},
    ],
)
async def test_a_plugin_change_cancelled_while_the_runtime_reloads_still_finishes(monkeypatch, command: dict) -> None:
    platform = FakePlatform(infer_s=0.02)
    reloads: list[set[str]] = []

    async def slow_reload(running, failed_gates) -> None:
        await asyncio.sleep(0.2)
        reloads.append({plugin.id for plugin in running})

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await install_demo(engine)
        monkeypatch.setattr(platform.plugin_runtime, "reload", slow_reload)
        saves: list[dict] = []
        monkeypatch.setattr(platform, "save_state", saves.append)
        await _cancelled_after(engine, command, 0.05)
        await asyncio.sleep(0.5)
        assert reloads == [set() if command["cmd"] != "plugin.secrets" else {"demo"}], "the runtime was never told"
        assert saves, "the change was never saved"


async def _chunks(data: bytes):
    yield data


async def test_print_library_registers_tags_and_starts_on_an_idle_printer() -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode", "printer_ids": [printer_id]})
        [record] = engine.state_event()["prints"]
        assert record["name"] == "benchy" and record["ext"] == "gcode" and record["size"] == len(PRUSA)
        assert record["printer_ids"] == [printer_id]
        assert record["meta"]["slicer"] == "PrusaSlicer 2.8.1" and record["meta"]["printer_model"] == "MK4"
        assert record["thumbnail"] == "image/png" and platform.files.blobs["abcd1234.thumb"] == b"BIG"

        platform.device_status = "Printing"
        await engine.handle({"cmd": "print.start", "id": "abcd1234", "printer_id": printer_id, "req_id": 5})
        refused = next(e for e in events if e["event"] == "error" and e.get("req_id") == 5)
        assert "printing" in refused["message"], "a busy printer is never sent a file"
        assert not any(url.endswith("/api/files/local") for _, url in platform.http_calls)

        platform.device_status = "Operational"
        await engine.handle({"cmd": "print.start", "id": "abcd1234", "printer_id": printer_id, "req_id": 6})
        upload = next(r for r in platform.http_requests if r["url"].endswith("/api/files/local"))
        assert upload["method"] == "POST" and upload["headers"]["X-Api-Key"] == "k"
        assert b'name="print"\r\n\r\ntrue' in upload["data"] and b'filename="benchy.gcode"' in upload["data"]
        assert PRUSA in upload["data"]
        assert any(e["event"] == "print_started" and e["printer_id"] == printer_id and e.get("req_id") == 6 for e in events)


async def test_a_printer_being_sent_a_file_is_not_sent_a_second(monkeypatch) -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    platform.device_status = "Operational"
    answer = platform.http

    async def slow_upload(method: str, url: str, **kwargs):
        if url.endswith("/api/files/local"):
            await asyncio.sleep(0.2)
        return await answer(method, url, **kwargs)

    monkeypatch.setattr(platform, "http", slow_upload)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode"})
        start = {"cmd": "print.start", "id": "abcd1234", "printer_id": printer_id}
        await asyncio.gather(engine.handle({**start, "req_id": 1}), engine.handle({**start, "req_id": 2}))
        assert [url for _, url in platform.http_calls if url.endswith("/api/files/local")] == ["http://op/api/files/local"]
        assert len(_of(events, "print_started")) == 1
        assert "already being sent a file" in next(e for e in _of(events, "error") if e.get("req_id") == 2)["message"]


async def _cancelled_after(engine: Engine, message: dict, seconds: float) -> None:
    task = asyncio.create_task(engine.handle(message, lambda event: None))
    await asyncio.sleep(seconds)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_a_camera_removal_cancelled_while_its_source_is_released_still_finishes() -> None:
    platform = FakePlatform()
    release = platform.release_camera

    async def slow_release(camera_id: str, source: dict) -> None:
        await asyncio.sleep(0.2)
        await release(camera_id, source)

    platform.release_camera = slow_release
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        camera = engine.cameras.values()[0]
        await _cancelled_after(engine, {"cmd": "camera.remove", "id": camera.id}, 0.05)
        await asyncio.sleep(0.5)
        assert not engine.cameras.values(), "the camera stayed registered"
        assert [m["camera_id"] for m in engine.monitors.values()] == [""], "its monitor stayed bound to it"
        assert platform.state["cameras"] == [], "state.json still lists it"


async def test_a_printer_removal_cancelled_while_its_connection_closes_still_finishes(monkeypatch) -> None:
    closed: list[dict | None] = []

    async def slow_close(config=None):
        await asyncio.sleep(0.2)
        closed.append(config)

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "close", slow_close)
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        printer_id = await _register_printer(engine)
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await _cancelled_after(engine, {"cmd": "printer.remove", "id": printer_id}, 0.05)
        await asyncio.sleep(0.5)
        assert not engine.printers.values(), "the printer stayed registered"
        assert engine.monitors[monitor_id]["printer_id"] == "", "its monitor kept the printer"
        assert platform.state["printers"] == [], "state.json still lists it"
        assert closed, "its connection was never closed"


async def test_a_monitor_removal_cancelled_while_its_frames_are_deleted_still_finishes(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    remove = platform.files.remove

    async def slow_remove(key: str) -> None:
        await asyncio.sleep(0.1)
        await remove(key)

    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await _finished_review(engine, 0.6)
        assert engine.state_event()["reviews"]
        monkeypatch.setattr(platform.files, "remove", slow_remove)
        await _cancelled_after(engine, {"cmd": "monitor.remove", "id": monitor_id}, 0.05)
        await asyncio.sleep(1.0)
        assert not engine.monitors, "the monitor stayed registered"
        assert not engine.state_event()["reviews"], "the prints of a monitor that is gone stayed listed"
        assert platform.state["monitors"] == []


async def test_a_print_start_cancelled_while_the_file_is_sent_says_so(monkeypatch) -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    platform.device_status = "Operational"

    async def slow_upload(http, config, filename, data) -> None:
        await asyncio.sleep(0.5)

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "print_file", slow_upload)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode"})
        await _cancelled_after(engine, {"cmd": "print.start", "id": "abcd1234", "printer_id": printer_id}, 0.1)
        errors = [e["message"] for e in _of(events, "error")]

    assert any("benchy" in message and "interrupted" in message for message in errors), errors
    assert not engine._starting


async def test_print_add_rewrites_temperatures_and_drops_a_file_it_cannot() -> None:
    from test_gcode import PRUSA_HEATED, bgcode

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA_HEATED))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "part.gcode", "nozzle": 230, "bed": None})
        [record] = engine.state_event()["prints"]
        assert record["meta"]["nozzle"] == 230.0 and record["meta"]["bed"] == 60.0
        stored = platform.files.blobs["abcd1234.gcode"]
        assert b"M109 S230\n" in stored and b"M190 S60\n" in stored and record["size"] == len(stored)

        await platform.files.store("bin00001.bgcode", _chunks(bgcode()))
        await engine.handle({"cmd": "print.add", "id": "bin00001", "filename": "part.bgcode", "nozzle": 230, "req_id": 7})
        assert any(e["event"] == "error" and e.get("req_id") == 7 and "binary gcode" in e["message"] for e in events)
        assert "bin00001.bgcode" not in platform.files.blobs, "a file that cannot take its temperatures is not kept"


async def test_a_print_with_an_absurd_estimate_is_refused_and_leaves_the_state_saveable() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        crafted = b"; estimated printing time (normal mode) = " + b"9" * 4300 + b"d\nG28\nM104 S210\n"
        await platform.files.store("abcd1234.gcode", _chunks(crafted))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "evil.gcode", "req_id": 3})
        assert any(e["event"] == "error" and e.get("req_id") == 3 and "a number in this file" in e["message"] for e in events)
        assert not engine.prints.values() and not set(platform.files.blobs), "the refused print left its file behind"
        json.dumps(engine.state_event(), allow_nan=False)
        json.dumps(platform.state if platform.state else {}, allow_nan=False)


async def test_a_failed_print_add_cannot_remove_another_prints_files() -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode"})
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "missing.bgcode", "req_id": 8})
        await engine.handle({"cmd": "print.add", "id": "../abcd1234", "filename": "missing.gcode", "req_id": 9})
        refused = [event.get("req_id") for event in events if event["event"] == "error" and "cannot be the id" in event["message"]]
        assert refused == [8, 9], "an id that names a print in the library or a path is refused"
        assert {"abcd1234.gcode", "abcd1234.thumb"} <= set(platform.files.blobs), "the print it named keeps its file and preview"
        assert [record["filename"] for record in engine.state_event()["prints"]] == ["benchy.gcode"]


async def test_print_start_honours_tags_and_formats() -> None:
    from test_gcode import PRUSA, sliced_3mf

    platform = FakePlatform()
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        first = await _register_printer(engine)
        await engine.handle({"cmd": "printer.add", "printer": {"name": "Second", **OCTOPRINT}})
        second = next(pid for pid in engine.printers.items if pid != first)
        await platform.files.store("tagged01.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "tagged01", "filename": "tagged.gcode", "printer_ids": [first]})
        await engine.handle({"cmd": "print.start", "id": "tagged01", "printer_id": second, "req_id": 1})
        assert any(e["event"] == "error" and e.get("req_id") == 1 and "not tagged for Second" in e["message"] for e in events)
        assert not platform.http_requests or not any(r["url"].endswith("/api/files/local") for r in platform.http_requests)

        await platform.files.store("bambu001.3mf", _chunks(sliced_3mf()))
        await engine.handle({"cmd": "print.add", "id": "bambu001", "filename": "plate.3mf", "printer_ids": [first], "req_id": 2})
        assert any(e["event"] == "error" and e.get("req_id") == 2 and "cannot print .3mf" in e["message"] for e in events)
        assert "bambu001.3mf" not in platform.files.blobs, "a refused upload leaves nothing behind"
        assert engine.prints.get("bambu001") is None

        await platform.files.store("free0001.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "free0001", "filename": "free.gcode"})
        await engine.handle({"cmd": "print.update", "id": "free0001", "patch": {"printer_ids": [first, first, second]}})
        assert engine.prints.get("free0001").printer_ids == [first, second]
        await engine.handle({"cmd": "print.update", "id": "free0001", "patch": {"printer_ids": []}})
        await engine.handle({"cmd": "print.start", "id": "free0001", "printer_id": second, "req_id": 3})
        assert any(e["event"] == "print_started" and e.get("req_id") == 3 for e in events), "an untagged file goes to any printer that prints it"


async def test_print_rename_remove_and_a_removed_printers_tag_stays() -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode", "printer_ids": [printer_id]})
        await engine.handle({"cmd": "print.update", "id": "abcd1234", "patch": {"name": "  Benchy   v2 "}})
        assert engine.prints.get("abcd1234").name == "Benchy v2"
        await engine.handle({"cmd": "print.update", "id": "missing", "patch": {"name": "x"}, "req_id": 9})
        assert any(e["event"] == "error" and e.get("req_id") == 9 for e in events)

        await engine.handle({"cmd": "printer.remove", "id": printer_id})
        other = await _register_printer(engine)
        await engine.handle({"cmd": "print.start", "id": "abcd1234", "printer_id": other, "req_id": 10})
        assert any(e["event"] == "error" and e.get("req_id") == 10 and "not tagged for" in e["message"] for e in events), (
            "a file tagged only for a printer that is gone starts nowhere"
        )
        await engine.handle({"cmd": "print.update", "id": "abcd1234", "patch": {"printer_ids": [other]}})
        assert engine.prints.get("abcd1234").printer_ids == [other], "tagging it again drops the printer that is gone"

        await engine.handle({"cmd": "print.remove", "id": "abcd1234"})
        assert engine.prints.get("abcd1234") is None
        assert platform.files.blobs == {}, "the file and its preview go with the record"
        assert engine.state_event()["prints"] == []


async def test_prints_survive_a_restart() -> None:
    from test_gcode import PRUSA

    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id = await _register_printer(engine)
        await platform.files.store("abcd1234.gcode", _chunks(PRUSA))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode", "name": "Boat", "printer_ids": [printer_id]})
        before = engine.state_event()["prints"]

    reborn = Engine(platform)
    await reborn.start()
    try:
        assert reborn.state_event()["prints"] == before
        assert reborn.prints.get("abcd1234").file_key == "abcd1234.gcode"
    finally:
        await reborn.stop()


async def test_the_frame_that_cancels_a_print_stays_in_that_prints_review(monkeypatch) -> None:
    """The poll reads the printer idle while it and the notifier are still answering, which must not end the review before the frame is kept."""
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http

    async def cancelling(method: str, url: str, **request: Any) -> tuple[int, Any]:
        if url == "http://ntfy/topic":
            await asyncio.sleep(0.3)
        if method == "POST" and "/api/job" in url:
            platform.device_status = "Operational"
            await asyncio.sleep(0.2)
        return await answer(method, url, **request)

    monkeypatch.setattr(platform, "http", cancelling)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, _events):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
        patch = {"printer_id": printer_id, "on_defect": "cancel", "cooldown_s": 0, "consecutive": 1, "notify": True}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await asyncio.sleep(0.5)
        platform.failing = True
        await asyncio.sleep(1.2)
        cancelled = engine.state_event()["reviews"]
        platform.failing = False
        platform.device_status = "Printing"
        await asyncio.sleep(0.5)
        platform.device_status = "Operational"
        await asyncio.sleep(0.3)
        both = engine.state_event()["reviews"]
    assert [(review["status"], review["alerts"]) for review in cancelled] == [("ready", 1)], "the cancelled print ends with its alert frame in it"
    assert [(review["status"], review["alerts"]) for review in both] == [("ready", 1), ("ready", 0)], "the next print starts a review of its own"


async def test_a_printer_that_does_not_answer_holds_up_nobody_elses_camera(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    _, release = await _one_slow_printer(platform, monkeypatch, "slow.lan")
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await _add_printers(engine, "slow.lan", "quick.lan")
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": engine.printers.values()[1].id}})
        await engine.watchdog.poll_devices()
        asleep = camera.in_use
        platform.device_status = "Printing"
        release.clear()
        poll = asyncio.create_task(engine.watchdog.poll_devices())
        for _ in range(50):
            if camera.in_use:
                break
            await asyncio.sleep(0.01)
        woken_meanwhile = camera.in_use
        release.set()
        await poll

    assert not asleep and woken_meanwhile, "a printer that started printing waited on another's answer before its camera woke"


async def test_a_poll_begun_before_a_pause_does_not_undo_the_read_made_after_it(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http
    hold = False
    held = asyncio.Event()
    release = asyncio.Event()

    async def http(method: str, url: str, **request: Any) -> tuple[int, Any]:
        nonlocal hold
        if method == "POST" and "/api/job" in url:
            platform.device_status = "Paused"
        answered = await answer(method, url, **request)
        if hold and method == "GET" and url.endswith("/api/job"):
            hold = False
            held.set()
            await release.wait()
        return answered

    monkeypatch.setattr(platform, "http", http)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1, "cooldown_s": 0}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await engine.watchdog.poll_devices()
        printer = engine.printers.get(printer_id)
        hold = True
        poll = asyncio.create_task(engine.watchdog.poll_devices())
        await asyncio.wait_for(held.wait(), 1.0)
        platform.failing = True
        for _ in range(100):
            if printer.reported_status == "paused":
                break
            await asyncio.sleep(0.01)
        release.set()
        await poll
        after_the_old_answer = printer.reported_status
        await asyncio.sleep(0.3)

    assert after_the_old_answer == "paused", "an answer from before the pause replaced the one read after it"
    assert [alert["action"] for alert in _of(events, "alert")] == ["pause"], "the paused print was paused again"


async def test_a_camera_that_is_slow_to_open_is_given_the_time_it_takes_by_a_plain_request(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(engine_module, "CAMERA_OPEN_WAIT_S", 0.6)
    platform = FakePlatform()
    open_camera = platform.open_camera

    async def slow_open(camera_id: str, source: dict):
        await asyncio.sleep(0.4)
        return await open_camera(camera_id, source)

    monkeypatch.setattr(platform, "open_camera", slow_open)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.request({"cmd": "camera.add", "name": "slow", "source": {"kind": "fake"}})
        assert len(engine.cameras.values()) == 1


async def test_refreshing_a_printers_cameras_is_given_the_time_each_takes_to_open(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(engine_module, "CAMERA_OPEN_WAIT_S", 0.3)
    platform = FakePlatform()
    open_camera = platform.open_camera

    async def slow_open(camera_id: str, source: dict):
        await asyncio.sleep(0.25)
        return await open_camera(camera_id, source)

    async def two_cameras(http, config):
        return [{"key": key, "name": key, "source": {"kind": "url", "url": f"http://op/{key}"}} for key in ("a", "b")]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", two_cameras)
    monkeypatch.setattr(platform, "open_camera", slow_open)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await _register_printer(engine)
        await engine.request({"cmd": "printer.cameras.refresh"})
        assert len(engine.cameras.values()) == 2


async def test_a_runtime_switch_is_given_the_time_the_model_takes_to_load(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(engine_module, "RUNTIME_LOAD_ALLOWANCE_S", 0.6)
    platform = FakePlatform()
    configure = platform.configure

    async def slow_configure(settings: dict) -> None:
        await asyncio.sleep(0.4)
        await configure(settings)

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        monkeypatch.setattr(platform, "configure", slow_configure)
        await engine.request({"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}})
        assert engine.settings["inference_runtime"] == "onnx"


async def test_a_poll_begun_before_a_manual_pause_does_not_undo_it(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http
    hold = False
    held = asyncio.Event()
    release = asyncio.Event()

    async def http(method: str, url: str, **request: Any) -> tuple[int, Any]:
        nonlocal hold
        if method == "POST" and "/api/job" in url:
            platform.device_status = "Paused"
        answered = await answer(method, url, **request)
        if hold and method == "GET" and url.endswith("/api/job"):
            hold = False
            held.set()
            await release.wait()
        return answered

    monkeypatch.setattr(platform, "http", http)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        patch = {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1, "cooldown_s": 0}
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": patch})
        await engine.watchdog.poll_devices()
        printer = engine.printers.get(printer_id)
        hold = True
        poll = asyncio.create_task(engine.watchdog.poll_devices())
        await asyncio.wait_for(held.wait(), 1.0)
        await engine.handle({"cmd": "printer.action", "id": printer_id, "action": "pause"})
        platform.failing = True
        release.set()
        await poll
        after_the_old_answer = printer.reported_status
        await asyncio.sleep(0.3)

    assert after_the_old_answer == "paused", "an answer from before a manual pause replaced the read after it"
    assert not _of(events, "alert"), "a print paused by hand was alerted on and sent a second pause"


async def test_a_monitor_switched_off_while_its_printer_answers_shows_no_alert() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.action_delay_s = 0.3
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1}})
        platform.failing = True
        await asyncio.wait_for(platform.action_started.wait(), 2.0)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await asyncio.sleep(0.8)
        monitor = engine.state_event()["monitors"][0]

    assert [alert["action"] for alert in _of(events, "alert")] == ["pause"], "the pause that went through is still announced"
    assert monitor["alert"] is None, "a monitor switched off got its alert back once the printer answered"


async def test_a_monitor_switched_off_forgets_that_its_printer_could_not_be_read(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.05)
    monkeypatch.setattr(watchdog, "GRACE_MIN_S", 0.0)
    monkeypatch.setattr(watchdog, "RECOVER_HOLD_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Detecting serial connection"
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        monitor_id = next(iter(engine.monitors))
        await engine.handle({"cmd": "settings.update", "patch": {"fault_grace_s": 0.2}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": printer_id}})
        await asyncio.sleep(1.0)
        warned = [e for e in _of(events, "warning") if "Cannot tell whether the printer" in e["message"]]
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        await asyncio.sleep(0.2)
        platform.device_status = "Printing"
        await asyncio.sleep(0.2)
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": True}})
        await asyncio.sleep(0.6)

    assert warned, "the unreadable printer was never warned about"
    assert not [e for e in _of(events, "warning") if e["recovered"]], "a monitor switched back on announced a recovery from before it was switched off"


async def test_a_stalled_camera_two_monitors_watch_is_attached_afresh_once(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "WATCH_TICK_S", 0.02)
    monkeypatch.setattr(watchdog, "STALL_GRACE_S", 0.1)
    monkeypatch.setattr(watchdog, "RESTART_AFTER_S", 0.05)
    platform = FakePlatform(infer_s=0.01)
    open_camera = platform.open_camera

    async def frozen(camera_id: str, source: dict[str, Any]) -> Any:
        opened = await open_camera(camera_id, source)
        opened.frozen = True
        return opened

    monkeypatch.setattr(platform, "open_camera", frozen)
    async with running_engine(platform, camera_fps=[20.0]) as (engine, _):
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": "second", "camera_id": camera.id}})
        await asyncio.sleep(0.8)
        released = list(platform.released_cameras)

    assert released == [camera.id], "each monitor tore the one camera down in turn"


async def test_a_printer_that_never_answers_a_pause_is_given_up_on(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    monkeypatch.setattr(watchdog, "ACT_DEADLINE_S", 0.2)
    platform = FakePlatform(infer_s=0.02)
    platform.action_delay_s = 30.0
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1}})
        platform.failing = True
        await asyncio.sleep(1.0)

    assert [alert["action"] for alert in _of(events, "alert")] == ["failed"], "the alert waited on a printer that was not answering"
    assert any("automatic pause failed: the printer did not answer within" in error["message"] for error in _of(events, "error"))


async def test_a_pause_refused_by_a_print_already_paused_is_not_a_failure(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform(infer_s=0.02)
    platform.reject_actions = True

    async def paused_at_the_printer() -> None:
        platform.device_status = "Paused"

    _answering(platform, paused_at_the_printer)
    async with running_engine(platform, camera_fps=[15.0]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id, "on_defect": "pause", "consecutive": 1}})
        await engine.watchdog.poll_devices()
        platform.failing = True
        await asyncio.sleep(1.0)
        watching = engine.state_event()["monitors"][0]["watching"]

    assert [alert["action"] for alert in _of(events, "alert")] == ["pause"], "a print that is paused was announced as one that could not be"
    assert platform.http_calls.count(("POST", "http://op/api/job")) == 1, "a paused printer was sent the pause again"
    assert not _of(events, "error") and not watching


async def test_a_printer_that_cannot_be_read_is_logged_once_with_the_reason(monkeypatch, caplog) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 3600.0)
    platform = FakePlatform()

    async def refused(method: str, url: str, **request: Any) -> tuple[int, Any]:
        raise ConnectionError("connection refused")

    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await _register_printer(engine)
        await asyncio.sleep(0.05)
        monkeypatch.setattr(platform, "http", refused)
        with caplog.at_level(logging.WARNING, logger="printguard.engine.watchdog"):
            await engine.watchdog.poll_devices()
            await engine.watchdog.poll_devices()

    assert [record.getMessage() for record in caplog.records if record.name == "printguard.engine.watchdog"] == [
        "printer 'P' could not be read: connection refused"
    ]

async def test_raising_a_cameras_detection_rate_brings_its_next_inference_forward() -> None:
    platform = FakePlatform(infer_s=0.01)
    async with running_engine(platform, camera_fps=[30.0]) as (engine, events):
        camera = engine.cameras.values()[0]
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"detect_fps": 0.1}})
        await asyncio.sleep(0.4)
        await engine.handle({"cmd": "camera.update", "id": camera.id, "patch": {"detect_fps": 30.0}})
        inferred = camera.last_done
        await asyncio.sleep(0.5)
        assert camera.last_done > inferred, "the camera waited out the interval of the rate it was lowered to"


async def test_a_camera_restart_during_a_runtime_switch_does_not_fail_the_switch() -> None:
    platform = FakePlatform(infer_s=0.01)
    platform.inference_blocked = True
    async with running_engine(platform, camera_fps=[30.0]) as (engine, _):
        await asyncio.wait_for(platform.inference_started.wait(), timeout=1.0)
        switch = asyncio.create_task(engine.request({"cmd": "settings.update", "patch": {"inference_runtime": "onnx"}}, timeout=2.0))
        await asyncio.sleep(0.05)
        await engine.restart_camera(engine.cameras.values()[0])
        await switch
        platform.inference_blocked = False
    assert platform.inference_runtime == "onnx"


async def test_stopping_cancels_an_inference_in_flight() -> None:
    """Left to finish, it scores its frame after the printers are closed and starts a defect response."""
    platform = FakePlatform(infer_s=0.3, failing=True)
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    printer_id = await _register_printer(engine)
    await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
    patch = {"camera_id": next(iter(engine.cameras.items)), "printer_id": printer_id, "consecutive": 1, "on_defect": "pause", "notify": True}
    await engine.handle({"cmd": "monitor.add", "monitor": patch})
    platform.inference_started.clear()
    await platform.inference_started.wait()
    await engine.stop()
    calls, seen = len(platform.http_calls), len(events)
    await asyncio.sleep(0.6)

    assert platform.http_calls[calls:] == [], "a printer or a notifier was called after the engine stopped"
    assert not _of(events[seen:], "alert")


async def test_a_printers_progress_does_not_push_an_alert_out_of_the_recent_events() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        engine.emit({"event": "alert", "monitor_id": "m", "score": 0.9, "action": "none"})
        for percent in range(engine_module.RECENT_EVENTS_MAX):
            engine.emit({"event": "device", "printer_id": "p", "status": "printing", "progress": percent})
        assert [event["event"] for event in engine.recent_events()] == ["alert"]
    finally:
        await engine.stop()


async def test_one_stream_written_two_ways_is_one_camera() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "camera.add", "source": {"kind": "url", "url": "  RTSP://Cam.local/live  "}})
        assert [camera.source["url"] for camera in engine.cameras.values()] == ["rtsp://Cam.local/live"], "the address is stored as it opens"
        for url in ("rtsp://cam.local/live", "rtsp://Cam.local/live#again", " Rtsp://Cam.local/live"):
            with pytest.raises(RuntimeError, match="already registered"):
                await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": url}})
        await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": "rtsp://cam.local/Live"}})
        assert len(engine.cameras.values()) == 2, "a path is told apart by its case"


@pytest.mark.parametrize(
    ("first", "again"),
    [
        ("rtsp://cam.local/live", "rtsp://cam.local:554/live"),
        ("rtsp://cam.local:554/live", "rtsp://cam.local/live"),
        ("http://cam.local/video", "http://cam.local:80/video"),
        ("https://cam.local/video", "https://cam.local:443/video"),
        ("http://cam.local:8090/video", "http://cam.local:08090/video"),
        ("http://127.0.0.1:8090/video", "http://127.1:8090/video"),
        ("http://127.0.0.1:8090/video", "http://2130706433:8090/video"),
        ("rtsp://cam.local/live", "rtsp://cam.local/live/"),
        ("rtsp://cam.local/live", "rtsp://cam.local/live?"),
        ("rtsp://cam.local/live", "rtsp://cam.local./live"),
        ("rtsp://cam.local/live", "rtsp://cam.local/%6Cive"),
        ("rtsp://cam.local/live", "rtsp://user:pw@cam.local/live"),
        ("rtsp://a:b@cam.local/live", "rtsp://c:d@cam.local/live"),
        ("http://cam.local/s?a=1&b=2", "http://cam.local/s?b=2&a=1"),
        ("http://cam.local/s?a=1&b=2", "http://cam.local/s?a=1&&b=2"),
        ("http://[::1]:8090/video", "http://[0:0:0:0:0:0:0:1]:8090/video"),
        ("http://cam.local", "http://cam.local/"),
        ("whep://cam.local/stream/whep", "whep://cam.local:80/stream/whep"),
        ("wheps://cam.local/stream/whep", "wheps://cam.local:443/stream/whep"),
        ("http://cam.local:8889/stream/whep", "whep://cam.local:8889/stream/whep"),
        ("https://cam.local/stream/whep", "wheps://cam.local/stream/whep"),
        ("http://cam.local/stream/whep", "whep://cam.local/stream/whep"),
    ],
)
async def test_every_way_of_writing_one_stream_is_one_camera(first: str, again: str) -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": first}})
        with pytest.raises(RuntimeError, match="already registered"):
            await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": again}})


@pytest.mark.parametrize(
    ("first", "other"),
    [
        ("rtsp://cam.local/live", "rtsp://cam.local/Live"),
        ("rtsp://cam.local/live", "rtsps://cam.local/live"),
        ("rtsp://cam.local/live", "rtsp://cam.local:555/live"),
        ("http://cam.local/video", "https://cam.local/video"),
        ("http://cam.local/video", "http://cam.local:443/video"),
        ("http://127.0.0.1/video", "http://127.0.0.2/video"),
        ("http://cam.local/s?a=1", "http://cam.local/s?a=2"),
        ("http://cam.local/a%2Fb", "http://cam.local/a/b"),
        ("whep://cam.local/stream/whep", "wheps://cam.local/stream/whep"),
        ("whep://cam.local:8889/stream/whep", "whep://cam.local:8890/stream/whep"),
    ],
)
async def test_streams_that_differ_are_told_apart(first: str, other: str) -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": first}})
        await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": other}})
        assert len(engine.cameras.values()) == 2


async def test_a_device_registered_by_hand_is_not_registered_again_when_the_deployment_declares_it() -> None:
    platform = FakePlatform()
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "USB cam", "declared": False}]
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.request({"cmd": "camera.add", "name": "bench cam", "source": {"kind": "device", "device_id": "/dev/video0"}})
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "USB cam", "declared": True}]
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        cameras = engine.cameras.values()
        assert [(camera.name, camera.declared) for camera in cameras] == [("bench cam", False)], "one device became two cameras"
        await engine.request({"cmd": "camera.remove", "id": cameras[0].id})


async def test_two_adds_of_one_stream_at_once_register_one_camera(monkeypatch) -> None:
    platform = FakePlatform()
    opening = platform.open_camera

    async def slow_open(camera_id: str, source: dict) -> object:
        await asyncio.sleep(0.1)
        return await opening(camera_id, source)

    monkeypatch.setattr(platform, "open_camera", slow_open)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        add = {"cmd": "camera.add", "source": {"kind": "url", "url": "rtsp://cam.local/live"}}
        await asyncio.gather(engine.handle(add), engine.handle(add))
        assert len(engine.cameras.values()) == 1
        assert [event["message"] for event in _of(events, "error")] == ["that camera is already registered"]
        await engine.handle({"cmd": "camera.remove", "id": next(iter(engine.cameras.items))})
        await engine.request(add)


async def test_a_printers_webcam_registered_by_hand_is_not_registered_again(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "url", "url": "http://op/webcam/?action=stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "camera.add", "source": {"kind": "url", "url": "http://op/webcam/?action=stream"}})
        await _register_printer(engine)
        await asyncio.sleep(0.1)
        assert [camera.printer_id for camera in engine.cameras.values()] == [None]


async def _slow_webcam(monkeypatch, platform: FakePlatform, url: str) -> None:
    opening = platform.open_camera

    async def slow_open(camera_id: str, source: dict) -> object:
        await asyncio.sleep(0.3)
        return await opening(camera_id, source)

    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "url", "url": url}}]

    monkeypatch.setattr(platform, "open_camera", slow_open)
    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)


async def test_a_webcam_added_by_hand_while_its_printer_is_opening_it_is_one_camera(monkeypatch) -> None:
    platform = FakePlatform()
    await _slow_webcam(monkeypatch, platform, "http://op/webcam/?action=stream")
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await _register_printer(engine)
        await asyncio.sleep(0.1)
        await engine.handle({"cmd": "camera.add", "source": {"kind": "url", "url": "http://op/webcam/?action=stream"}})
        await asyncio.sleep(0.5)
        assert [camera.printer_id is not None for camera in engine.cameras.values()] == [True]
        assert [event["message"] for event in _of(events, "error")] == ["that camera is already registered"]


async def test_a_printers_webcam_is_one_camera_when_a_hand_add_is_still_opening_it(monkeypatch) -> None:
    platform = FakePlatform()
    await _slow_webcam(monkeypatch, platform, "http://op/webcam/?action=stream")
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        add = asyncio.ensure_future(engine.handle({"cmd": "camera.add", "source": {"kind": "url", "url": "http://op/webcam/?action=stream"}}))
        await asyncio.sleep(0.1)
        await _register_printer(engine)
        await add
        await asyncio.sleep(0.5)
        assert [camera.printer_id for camera in engine.cameras.values()] == [None]


async def test_a_printer_moved_onto_a_stream_that_is_already_a_camera_leaves_its_camera_where_it_was(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "url", "url": f"{config['base_url']}/webcam/?action=stream"}}]

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "camera.add", "source": {"kind": "url", "url": "http://new/webcam/?action=stream"}})
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.1)
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://new", "api_key": "k"}}})
        await asyncio.sleep(0.1)
        assert sorted(camera.source["url"] for camera in engine.cameras.values()) == ["http://new/webcam/?action=stream", "http://op/webcam/?action=stream"]
        assert [event["message"] for event in _of(events, "warning")] == ["Could not move the camera 'Shop cam' of printer 'P': that stream is already registered"]


async def test_a_camera_cannot_be_registered_on_the_stream_the_hub_publishes_for_another() -> None:
    async with running_engine(FakePlatform(), camera_fps=[10.0]) as (engine, _):
        (camera_id,) = engine.cameras.items
        with pytest.raises(RuntimeError, match="already registered"):
            await engine.request({"cmd": "camera.add", "source": {"kind": "path", "path": camera_id}})
        assert len(engine.cameras.items) == 1


async def test_a_saved_stream_address_that_cannot_be_read_does_not_break_other_cameras() -> None:
    platform = FakePlatform()
    platform.state = {"cameras": [{**_FAKE_CAMERA, "source": {"kind": "url", "url": "http://admin:pa[ss@10.0.0.9/stream"}}]}
    platform.devices = [{"kind": "device", "device_id": "/dev/video0", "label": "USB cam", "declared": True}]
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await engine.request({"cmd": "discover"})
        await engine.request({"cmd": "camera.add", "source": {"kind": "url", "url": "rtsp://10.0.0.7/other"}})
        assert len(engine.cameras.items) == 3


async def test_a_removal_whose_clean_up_fails_is_still_a_removal(monkeypatch) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        await platform.files.store("abcd1234.gcode", _chunks(b"G1 X1\n"))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "part.gcode"})
        camera_id = next(iter(engine.cameras.items))
        (monitor_id,) = engine.monitors

        async def refused(*args) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(platform.files, "remove", refused)
        monkeypatch.setattr(platform, "release_camera", refused)
        monkeypatch.setattr(engine.reviews, "forget", refused)
        await engine.request({"cmd": "print.remove", "id": "abcd1234"})
        await engine.request({"cmd": "camera.remove", "id": camera_id})
        await engine.request({"cmd": "monitor.remove", "id": monitor_id})
        assert not engine.prints.items and not engine.cameras.items and not engine.monitors
        assert (platform.state["prints"], platform.state["cameras"], platform.state["monitors"]) == ([], [], []), "the saved state still holds what was removed"
        assert [event["message"] for event in _of(events, "warning")] == [
            "Could not delete the stored file of 'part': [Errno 13] Permission denied",
            "Could not delete the preview of 'part': [Errno 13] Permission denied",
            "Could not release the camera 'cam10.0': [Errno 13] Permission denied",
            "Could not delete the kept frames of a removed monitor: [Errno 13] Permission denied",
        ]


async def test_removing_what_is_not_there_is_an_error() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        for kind in ("monitor", "camera", "printer", "print", "token"):
            with pytest.raises(RuntimeError, match=f"^no {kind} nope$"):
                await engine.request({"cmd": f"{kind}.remove", "id": "nope"})
        with pytest.raises(RuntimeError, match="^missing 'id'$"):
            await engine.request({"cmd": "monitor.update"})


async def test_a_monitor_is_not_bound_to_a_camera_or_printer_that_is_not_registered() -> None:
    async with running_engine(FakePlatform(), camera_fps=[10.0]) as (engine, _):
        monitor_id = next(iter(engine.monitors))
        with pytest.raises(RuntimeError, match="^no camera nope$"):
            await engine.request({"cmd": "monitor.add", "monitor": {"camera_id": "nope"}})
        with pytest.raises(RuntimeError, match="^no printer nope$"):
            await engine.request({"cmd": "monitor.update", "id": monitor_id, "patch": {"printer_id": "nope"}})
        await engine.request({"cmd": "monitor.add", "monitor": {"name": "later", "camera_id": "", "printer_id": ""}})
        assert [monitor["printer_id"] for monitor in engine.monitors.values()] == ["", ""]


async def test_a_value_a_setting_does_not_take_is_refused_rather_than_rewritten() -> None:
    async with running_engine(FakePlatform(), camera_fps=[10.0]) as (engine, _):
        monitor_id, camera_id = next(iter(engine.monitors)), next(iter(engine.cameras.items))
        await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"on_defect": "pause"}})
        before = (dict(engine.monitors[monitor_id]), engine.cameras.get(camera_id).persisted(), dict(engine.settings))
        refused = [
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"alert": {"score": 0.99, "action": "pause", "ts": 1}}}, "a monitor has no alert setting"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"on_defect": "Pause"}}, "on_defect is one of none, pause, cancel"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": "false"}}, "enabled is true or false"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"name": None}}, "name is text"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"crop": [0, 0, 1, 1]}}, "a crop holds x, y, w and h"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"name": None}}, "name is text"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"source": {"kind": "url"}}}, "a camera has no source setting"),
            ({"cmd": "settings.update", "patch": {"volume": 3}}, "there is no volume setting"),
            ({"cmd": "settings.update", "patch": {"theme": "dark", "volume": 3}}, "there is no volume setting"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"port": True}}}, "MQTT port"),
            ({"cmd": "settings.update", "patch": {"update_check": "banana"}}, "update_check is true or false"),
            ({"cmd": "settings.update", "patch": {"catalogue_url": 5}}, "catalogue_url is an address"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "port": 0}}}, "MQTT port"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True, "host": "  "}}}, "MQTT needs the broker's host"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True}}}, "MQTT needs the broker's host"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"host": 5}}}, "MQTT host is text"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "enabled": "yes"}}}, "MQTT enabled is true or false"),
            ({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "keepalive": 5}}}, "mqtt has no keepalive setting"),
            ({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": 5}}}}, "Topic URL is text"),
            ({"cmd": "printer.add", "printer": {"provider": "octoprint", "config": {"base_url": 5, "api_key": ["k"]}}}, "Base URL is text"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"rotation": False}}, "rotation is 0, 90, 180 or 270"),
            ({"cmd": "settings.update", "patch": {"fault_grace_s": "120"}}, "fault_grace_s must be a number"),
            ({"cmd": "settings.update", "patch": {"fault_grace_s": True}}, "fault_grace_s must be a number"),
            ({"cmd": "settings.update", "patch": {"preheat": None}}, "preheat is a list of presets"),
            ({"cmd": "settings.update", "patch": {"preheat": [{"name": "PLA", "nozzle": "210", "bed": 60}]}}, "nozzle temperature must be a number"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"threshold": True}}, "threshold must be a number"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"threshold": "0.5"}}, "threshold must be a number"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"threshold": 10**400}}, "threshold must be a finite number"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"consecutive": True}}, "consecutive must be a number"),
            ({"cmd": "monitor.update", "id": monitor_id, "patch": {"cooldown_s": "30"}}, "cooldown_s must be a number"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"brightness": True}}, "brightness must be a number"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"detect_fps": "5"}}, "detect_fps must be a number"),
            ({"cmd": "camera.update", "id": camera_id, "patch": {"crop": {"x": "0.1", "y": 0, "w": 0.5, "h": 0.5}}}, "crop x must be a number"),
        ]
        for command, reason in refused:
            with pytest.raises(RuntimeError, match=reason):
                await engine.request(command)
        assert (dict(engine.monitors[monitor_id]), engine.cameras.get(camera_id).persisted(), dict(engine.settings)) == before
        assert not engine.printers.values()


async def test_a_command_whose_name_is_not_text_is_an_unknown_command() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": [], "req_id": 1})
        await engine.handle({"cmd": {}, "req_id": 2})
        assert [event["req_id"] for event in _of(events, "error")] == [1, 2]


async def test_a_command_that_fails_applies_none_of_itself() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await platform.files.store("abcd1234.gcode", _chunks(b"G1 X1\n"))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "part.gcode", "name": "Original"})
        with pytest.raises(RuntimeError, match="no printer ghost"):
            await engine.request({"cmd": "print.update", "id": "abcd1234", "patch": {"name": "Renamed", "printer_ids": ["ghost"]}})
        assert engine.prints.get("abcd1234").name == "Original"

        await engine.handle({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": plugin_zip()})
        held = list(engine.plugins.get("demo").granted)
        with pytest.raises(RuntimeError, match="have not been accepted"):
            await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["state:read"], "enabled": True}})
        assert engine.plugins.get("demo").granted == held


async def test_a_printer_camera_that_cannot_be_listed_or_opened_is_a_warning(monkeypatch) -> None:
    async def webcam(http, config):
        return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "device", "device_id": "/dev/gone"}}]

    async def unlisted(http, config):
        raise OSError("connection refused")

    monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", webcam)
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await _register_printer(engine)
        await asyncio.sleep(0.1)
        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", unlisted)
        await engine.handle({"cmd": "printer.cameras.refresh"})
        assert [event["message"] for event in _of(events, "warning")] == [
            "Could not open the camera 'Shop cam' of printer 'P': no device at /dev/gone",
            "Could not list the cameras of printer 'P': connection refused",
        ]


async def test_a_wrong_shaped_record_is_dropped_at_start_and_the_rest_load(caplog) -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await _register_printer(engine)
        await engine.request({"cmd": "token.create", "name": "t", "scope": "read"})
    good = platform.state
    platform.state = {
        **good,
        "tokens": [{"id": "t9", "surprise": 1}, *good["tokens"]],
        "printers": [None, *good["printers"]],
        "monitors": [{"name": "no id"}, {"id": "m9", "on_defect": "explode"}, *good["monitors"]],
        "reviews": ["text", {"id": "r9"}],
        "prints": [{"id": "p9"}],
        "cameras": [{"id": "c9"}, *good["cameras"]],
    }
    restarted = Engine(platform)
    with caplog.at_level(logging.WARNING, logger="printguard.engine.engine"):
        await restarted.start()
    try:
        state = restarted.state_event()
        assert [len(state[kind]) for kind in ("tokens", "printers", "monitors", "reviews", "prints", "cameras")] == [1, 1, 1, 0, 0, 1]
    finally:
        await restarted.stop()
    assert caplog.text.count("could not be read and was dropped") == 8
    assert len(restarted.startup_warnings) == 8


async def test_a_monitor_bound_to_a_printer_dropped_at_start_is_unlinked_with_a_warning() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        printer_id = await _register_printer(engine)
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"printer_id": printer_id, "on_defect": "pause"}})
    saved = platform.state
    platform.state = {**saved, "printers": [{**saved["printers"][0], "reported_status": ["idle"]}]}
    restarted = Engine(platform)
    await restarted.start()
    try:
        monitor = next(iter(restarted.monitors.values()))
        assert monitor["printer_id"] == "" and monitor["on_defect"] == "pause"
        assert len(restarted.startup_warnings) == 2 and "no longer pauses" in restarted.startup_warnings[1], restarted.startup_warnings
    finally:
        await restarted.stop()


async def test_a_print_record_dropped_at_start_says_how_long_its_file_is_kept() -> None:
    platform = FakePlatform()
    platform.state = {"prints": [{"id": "abcd1234", "filename": "benchy.gcode"}], "reviews": [{"id": "a1b2c3"}]}
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        assert engine.dropped_ids == {"abcd1234", "a1b2c3"}
        assert all("its file stays in the data directory until the hub next starts" in warning for warning in engine.startup_warnings) and len(engine.startup_warnings) == 2


_FAKE_CAMERA = {"id": "c1", "name": "n", "source": {"kind": "fake"}, "max_fps": 15.0}
_FAKE_REVIEW = {"id": "r1", "monitor_id": "m1", "started": 1.0, "spacing_s": 60.0, "ended": 2.0}
_FAKE_FRAME = {"id": "f1", "ts": 1.5, "score": 0.9, "kind": "alert", "action": "none", "size": 6}
_QUEUED_REVIEW = {
    **_FAKE_REVIEW,
    "status": "queued",
    "frames": [_FAKE_FRAME],
    "submission": {"labels": {"f1": "failure"}, "printer": "", "sent": [], "code": "rate_limited", "retry_at": 9e9},
}
_FAKE_TOKEN = {"id": "t1", "name": "t", "scope": "read", "hash": "0" * 64, "hint": "pg_abc…", "created": 1.0}


@pytest.mark.parametrize(
    "state",
    [
        {"settings": {"notifiers": []}},
        {"settings": {"notifiers": {"ntfy": "http://ntfy/topic"}}},
        {"settings": {"mqtt": None}},
        {"settings": {"catalogue_url": None}},
        {"settings": {"update_check": "yes"}},
        {"settings": {"fault_grace_s": "120"}},
        {"settings": {"preheat": None}},
        {"settings": {"feedback": "on"}},
        {"settings": {"inference_runtime": "tflite"}},
        {"cameras": [{**_FAKE_CAMERA, "source": "rtsp://h/s"}]},
        {"cameras": [{**_FAKE_CAMERA, "source": {"kind": "url", "url": 5}}]},
        {"cameras": [{**_FAKE_CAMERA, "max_fps": None}]},
        {"cameras": [{**_FAKE_CAMERA, "max_fps": 10**400}]},
        {"cameras": [{**_FAKE_CAMERA, "name": 5}]},
        {"cameras": [{**_FAKE_CAMERA, "brightness": "bright"}]},
        {"printers": [{"id": "p1", "name": "P", **OCTOPRINT, "reported_status": ["idle"]}]},
        {"reviews": [{**_FAKE_REVIEW, "frames": None}]},
        {"reviews": [{**_FAKE_REVIEW, "frames": [{"id": "f"}]}]},
        {"reviews": [{**_FAKE_REVIEW, "status": "queued"}]},
        {"reviews": [{**_FAKE_REVIEW, "status": "later"}]},
        *({"reviews": [{**_QUEUED_REVIEW, "monitor_id": junk}]} for junk in ([], {}, None, 5)),
        *({"reviews": [{**_QUEUED_REVIEW, "submission": {**_QUEUED_REVIEW["submission"], "retry_at": junk}}]} for junk in ("x", [1], {"a": 1}, True)),
        {"reviews": [{**_QUEUED_REVIEW, "submission": {key: value for key, value in _QUEUED_REVIEW["submission"].items() if key != "retry_at"}}]},
        {"reviews": [{**_QUEUED_REVIEW, "submission": {**_QUEUED_REVIEW["submission"], "labels": {"f1": "maybe"}}}]},
        {"reviews": [{**_QUEUED_REVIEW, "submission": {**_QUEUED_REVIEW["submission"], "printer": ["Voron"]}}]},
        {"reviews": [{**_QUEUED_REVIEW, "frames": [{key: value for key, value in _FAKE_FRAME.items() if key != "action"}]}]},
        *({"reviews": [{**_QUEUED_REVIEW, "frames": [{**_FAKE_FRAME, "ts": junk}]}]} for junk in (None, "x", [], {}, True)),
        {"reviews": [{**_QUEUED_REVIEW, "frames": [{**_FAKE_FRAME, "kind": "other"}]}]},
        *({"tokens": [{**_FAKE_TOKEN, "hash": junk}]} for junk in ([], {}, None, 5)),
        {"tokens": [{**_FAKE_TOKEN, "scope": "root"}]},
        {"tokens": [{**_FAKE_TOKEN, "created": "now"}]},
        {"monitors": [{"id": "m1", "threshold": 10**400}]},
        {"monitors": [{"id": "m1", "threshold": True}]},
        {"prints": [{"id": "p", "name": "n", "filename": "f.gcode", "ext": "gcode", "size": 1, "printer_ids": None, "uploaded": 1, "meta": {}}]},
        {"prints": [{"id": "p", "name": "n", "filename": "f.gcode", "ext": "gcode", "size": "big", "printer_ids": [], "uploaded": 1, "meta": {}}]},
    ],
)
async def test_a_stored_value_of_the_wrong_kind_is_dropped_with_a_warning_and_the_hub_starts(state: dict) -> None:
    platform = FakePlatform()
    platform.state = state
    engine = Engine(platform)
    await engine.start()
    try:
        assert len(engine.startup_warnings) == 1, engine.startup_warnings
        json.dumps(engine.state_event(), allow_nan=False)
        assert engine.reviews.public() == []
        await engine.request({"cmd": "settings.update", "patch": {"theme": "dark"}})
    finally:
        await engine.stop()


async def test_a_queued_review_and_a_token_as_saved_are_restored() -> None:
    platform = FakePlatform()
    platform.state = {"reviews": [_QUEUED_REVIEW], "tokens": [_FAKE_TOKEN]}
    engine = Engine(platform)
    await engine.start()
    try:
        assert engine.startup_warnings == []
        assert [(review["status"], review["retry_at"]) for review in engine.reviews.public()] == [("queued", 9e9)]
        assert engine.token_scopes() == {"0" * 64: "read"}
    finally:
        await engine.stop()


async def test_a_stored_setting_of_the_wrong_kind_goes_back_to_its_default() -> None:
    platform = FakePlatform()
    platform.state = {"settings": {"notifiers": [], "fault_grace_s": "120", "feedback": "on", "theme": "dark"}}
    engine = Engine(platform)
    await engine.start()
    try:
        assert (engine.settings["notifiers"], engine.settings["fault_grace_s"], engine.settings["feedback"]) == ({}, watchdog.GRACE_DEFAULT_S, "ask")
        assert engine.settings["theme"] == "dark", "a setting that reads is kept"
    finally:
        await engine.stop()


async def test_a_monitor_stored_with_no_printer_is_kept_with_its_printer_cleared() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        pass
    saved = platform.state
    platform.state = {**saved, "monitors": [{**saved["monitors"][0], "printer_id": None}]}
    restarted = Engine(platform)
    await restarted.start()
    try:
        assert [monitor["printer_id"] for monitor in restarted.monitors.values()] == [""]
        assert restarted.startup_warnings == []
    finally:
        await restarted.stop()


async def test_what_start_dropped_or_worked_around_is_kept_for_a_dashboard_that_connects_later() -> None:
    platform = FakePlatform()
    platform.notices = [Notice("Intel GPU cannot run the model, so detection is not using it: out of memory")]
    manifest = {
        "id": "local-thing",
        "name": "Local thing",
        "version": "1.0.0",
        "permissions": ["net"],
        "reasons": {"net": "reads my printer"},
        "urls": ["http://127.1/*"],
    }
    platform.state = {
        "monitors": [{"id": "m9", "name": "Bench", "on_defect": "explode"}],
        "plugins": [{"id": "local-thing", "manifest": manifest, "sources": {}, "digests": {}, "source": {"kind": "file"}, "granted": [], "installed": 1.0}],
        "settings": {"glass": {"opacity": 0.4, "tone": "x"}},
    }
    engine = Engine(platform)
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        heard: list[dict] = []
        engine.add_sink(heard.append)
        platform.notices = [Notice("live view unavailable: refused")]
        await asyncio.sleep(1.2)
        warnings = engine.state_event()["startup_warnings"]
        kept = engine.plugins.get("local-thing")
    finally:
        await engine.stop()

    assert "Intel GPU cannot run the model, so detection is not using it: out of memory" in warnings
    assert any("saved monitor (Bench)" in warning and "on_defect" in warning for warning in warnings), warnings
    assert any("Plugin Local thing now needs Reach your own network" in warning for warning in warnings), warnings
    assert any("glass" in warning for warning in warnings), warnings
    assert len(warnings) == 4, "something raised after start was kept with what start raised"
    assert heard[0]["startup_warnings"] == warnings, "a dashboard connecting later is handed them in its first snapshot"
    assert not kept.enabled and "net:local" in kept.manifest["permissions"], "a plugin saved by 2.5 lost its data, or ran on a grant nobody gave"


async def test_a_wrong_shaped_layout_is_reset_without_the_theme() -> None:
    platform = FakePlatform()
    theme = {"id": "t1", "name": "Mine", "base": "dark", "colors": {"accent": "#112233"}}
    glass = {"opacity": 0.4, "tone": 0.2}
    platform.state = {"settings": {"theme": "t1", "themes": [theme], "glass": glass, "layout": {"monitors": {"order": ["m1"]}, "stray": 5}}}
    engine = Engine(platform)
    await engine.start()
    await engine.stop()
    assert (engine.settings["theme"], engine.settings["themes"], engine.settings["glass"]) == ("t1", [theme], glass)
    assert engine.settings["layout"] == {}


async def test_editing_an_idle_printers_connection_does_not_make_a_print(monkeypatch) -> None:
    """The edit forgets the printer's status, so its monitor watches until the next poll says idle again."""
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.3)
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 20.0}})
        printer_id = await _register_printer(engine)
        await asyncio.sleep(0.5)
        await engine.handle({"cmd": "monitor.add", "monitor": {"camera_id": next(iter(engine.cameras.items)), "printer_id": printer_id}})
        for attempt in range(3):
            config = {"base_url": f"http://op{attempt}", "api_key": "k"}
            await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": config}})
            await asyncio.sleep(0.5)
        assert engine.printers.get(printer_id).reported_status == "idle"
        assert engine.state_event()["reviews"] == [] and not platform.files.blobs


async def test_prints_sent_together_register_the_hub_once(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.1)
    platform = FakePlatform(infer_s=0.02)
    registered: list[str] = []
    hubs: set[str] = set()
    passthrough = platform.http

    async def inbox(method: str, url: str, **request) -> tuple[int, object]:
        if url == f"{feedback.ENDPOINT}/register":
            await asyncio.sleep(0.05)
            registered.append(f"{len(registered):032x}.{'b' * 64}")
            return 201, {"token": registered[-1]}
        if url == f"{feedback.ENDPOINT}/frame":
            hubs.add(request["headers"]["Authorization"])
            return 201, {}
        return await passthrough(method, url, **request)

    monkeypatch.setattr(platform, "http", inbox)
    async with running_engine(platform, camera_fps=[10.0, 12.0]) as (engine, _):
        await asyncio.sleep(0.5)
        for monitor_id in list(engine.monitors):
            await engine.handle({"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": False}})
        for review in engine.state_event()["reviews"]:
            await engine.handle({"cmd": "review.send", "id": review["id"]})
        await asyncio.sleep(0.6)
        sent = [review["status"] for review in engine.state_event()["reviews"]]

    assert sent == ["sent", "sent"]
    assert len(registered) == 1 and hubs == {f"Bearer {registered[0]}"}, "frames went under more than one hub id"


async def test_a_frame_being_stored_as_the_review_is_switched_off_is_not_kept(monkeypatch) -> None:
    platform = FakePlatform(infer_s=0.02)
    encode = platform.encode_jpeg
    storing = asyncio.Event()

    async def slow_encode(rgb: np.ndarray) -> bytes | None:
        storing.set()
        await asyncio.sleep(0.3)
        return await encode(rgb)

    monkeypatch.setattr(platform, "encode_jpeg", slow_encode)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await storing.wait()
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": "off"}})
        await asyncio.sleep(0.5)
        assert not platform.files.blobs and [review["frames"] for review in engine.state_event()["reviews"]] == [0]


async def test_a_private_catalogues_credentials_are_scrubbed_from_a_report() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        private = "https://reader:hunter2pass@raw.example.com/catalogue.json?token=s3cr3tvalue"
        await engine.handle({"cmd": "settings.update", "patch": {"catalogue_url": private}})
        assert reports.diagnostics(engine)["settings"]["custom_catalogue"] is True
        assert "raw.example.com" not in json.dumps(reports.diagnostics(engine))
        assert {"hunter2pass", "token=s3cr3tvalue"} <= reports.collect_secrets(engine)


async def test_a_print_none_of_whose_frames_could_be_sent_is_not_called_sent(monkeypatch) -> None:
    monkeypatch.setattr(reviews, "SPACED_START_S", 0.2)
    platform = FakePlatform(infer_s=0.02)
    uploads = _inbox(platform, monkeypatch)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        review = await _finished_review(engine, 0.5)
        platform.files.blobs.clear()
        await engine.handle({"cmd": "review.send", "id": review["id"], "req_id": 7})
        outcome = await _sent(events)
        waiting = engine.state_event()["reviews"][0]

    assert not uploads and not outcome["ok"]
    assert (waiting["status"], waiting["sent"], waiting["chosen"]) == ("ready", 0, 0), "it can be sent again or dismissed"
    assert [(event["message"], event["req_id"]) for event in _of(events, "error")] == [("none of that print's frames could be sent", 7)]


@pytest.mark.parametrize("feedback_setting, ended_as", [("ask", "ready"), ("off", "dismissed")])
async def test_a_monitor_with_no_printer_ends_its_print_after_a_day(monkeypatch, feedback_setting: str, ended_as: str) -> None:
    """With the review off no frame is sampled, so the day has to be noticed without one."""
    monkeypatch.setattr(reviews, "UNLINKED_PRINT_S", 0.4)
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.05)
    platform = FakePlatform(infer_s=0.02, failing=True)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, _):
        await engine.handle({"cmd": "settings.update", "patch": {"feedback": feedback_setting}})
        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"cooldown_s": 0, "consecutive": 1}})
        await asyncio.sleep(1.5)
        prints = engine.state_event()["reviews"]

    assert len(prints) >= 3, "every alert went into one endless print"
    assert {review["status"] for review in prints[:-1]} == {ended_as}


def test_a_uuid_in_a_camera_path_is_scrubbed_and_a_punctuated_name_is_not() -> None:
    assert reports.scrub_url("rtsps://nvr.local:7441/0b9f3c1e-8a41-4f6e-9d2b-6f1c2a7e5d10?enableSrtp") == "rtsps://nvr.local:7441/[redacted]?enableSrtp"
    assert reports.url_secrets("rtsps://nvr.local:7441/0b9f3c1e-8a41-4f6e-9d2b-6f1c2a7e5d10") == {"0b9f3c1e-8a41-4f6e-9d2b-6f1c2a7e5d10"}
    assert reports.scrub_url("rtsp://cam.local/h264Preview_01_main") == "rtsp://cam.local/h264Preview_01_main"


SECRET_PRINTER = {"base_url": "http://opuser:PRINTERPASS-9d1@octopi.local", "api_key": "octo-KEY-4f7a2c"}
SECRET_MQTT = {"enabled": False, "host": "broker", "username": "pg", "password": "mqtt-PASS-77b1e0"}
SECRET_CAMERA = "rtsp://viewer:CAMPASS-2e6d@192.168.1.60/stream?token=camtok-51c9"
SECRET_BAMBU = {"kind": "bambu", "host": "192.168.1.70", "access_code": "BAMBU-code-8842"}
SECRET_CATALOGUE = "https://reader:CATPASS-6a0f@raw.example.com/catalogue.json?token=cattok-3b7d"
STORED_SECRETS = ("PRINTERPASS-9d1", "octo-KEY-4f7a2c", "mqtt-PASS-77b1e0", "CAMPASS-2e6d", "camtok-51c9", "BAMBU-code-8842", "CATPASS-6a0f", "cattok-3b7d")


def _secret_notifiers() -> tuple[dict[str, dict[str, str]], list[str]]:
    """A config for every notifier with a value of its own in each secret field, and those values."""
    configs: dict[str, dict[str, str]] = {}
    values: list[str] = []
    for provider, adapter in NOTIFIERS.items():
        properties = adapter.schema.get("properties", {})
        config = {key: "9" for key in adapter.schema.get("required", [])}
        for key in adapter.secret_keys():
            value = f"{provider}-{key}-SECRET-5c3e"
            values.append(value)
            config[key] = f"https://hooks.example/{value}" if properties[key].get("format") == "uri" else value
        configs[provider] = config
    return configs, values


async def _seed_secrets(engine: Engine) -> tuple[str, list[str]]:
    """Stores a secret everywhere the engine keeps one.

    Returns:
        The printer's id and every secret value stored.
    """
    notifiers, notifier_secrets = _secret_notifiers()
    await engine.handle({"cmd": "printer.add", "printer": {"name": "P", "provider": "octoprint", "config": SECRET_PRINTER}})
    printer_id = next(iter(engine.printers.items))
    await engine.handle({"cmd": "settings.update", "patch": {"notifiers": notifiers, "mqtt": SECRET_MQTT, "catalogue_url": SECRET_CATALOGUE}})
    await engine.handle({"cmd": "camera.add", "name": "door", "source": {"kind": "url", "url": SECRET_CAMERA}})
    engine.cameras.add(Camera(id="chamber", name="Chamber", source=dict(SECRET_BAMBU), printer_id=printer_id, max_fps=5.0))
    return printer_id, [*STORED_SECRETS, *notifier_secrets]


def _leaked(payload: object, secrets: list[str]) -> list[str]:
    text = json.dumps(payload, default=str)
    return [secret for secret in secrets if secret in text]


async def test_no_stored_secret_is_in_the_state_or_in_any_event() -> None:
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http

    async def quoting_its_key(method: str, url: str, **kwargs):
        if "unreachable" in url:
            raise OSError(f"refused {url} with {kwargs.get('headers')}")
        return await answer(method, url, **kwargs)

    platform.http = quoting_its_key
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id, secrets = await _seed_secrets(engine)
        state = engine.state_event()
        shown = state["printers"][0]
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "Renamed", "config": shown["config"]}})
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": shown["config"]}, events.append)
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": {"base_url": "http://unreachable"}}, events.append)
        engine.printers.get(printer_id).config = {"base_url": "http://unreachable", "api_key": "octo-KEY-4f7a2c"}
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": {"base_url": "http://unreachable"}}, events.append)
        engine.printers.get(printer_id).config = dict(SECRET_PRINTER)
        for provider in NOTIFIERS:
            await engine.handle({"cmd": "notify.test", "provider": provider, "config": state["settings"]["notifiers"][provider]}, events.append)
        await engine.handle({"cmd": "settings.update", "patch": {key: state["settings"][key] for key in ("notifiers", "mqtt", "catalogue_url")}})
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "elsewhere"}}})
        await engine.handle({"cmd": "report.bundle"})
        final = engine.state_event()
        saved = json.dumps(platform.state)

    assert _leaked(state, secrets) == [] and _leaked(final, secrets) == []
    assert _leaked(events, secrets) == []
    tests = _of(events, "printer_test")
    assert [test["ok"] for test in tests] == [True, False, False]
    assert "API key" in tests[1]["error"] and "refused" in tests[2]["error"]
    assert all(secret in saved for secret in secrets), "the hub no longer holds what it needs to sign in"
    assert shown["config"] == {"base_url": "http://octopi.local"} and shown["secrets_set"] == ["api_key"]
    assert state["secrets_set"] == {
        "notifiers": {provider: sorted(adapter.secret_keys()) for provider, adapter in NOTIFIERS.items()},
        "mqtt": ["password"],
    }
    assert state["settings"]["mqtt"] == {"enabled": False, "host": "broker", "username": "pg"}
    assert all(not set(config) & NOTIFIERS[provider].secret_keys() for provider, config in state["settings"]["notifiers"].items())
    assert state["settings"]["catalogue_url"] == "https://raw.example.com/[redacted]?token=[redacted]"
    sources = {camera["id"]: camera["source"] for camera in state["cameras"]}
    assert sources["chamber"] == {"kind": "bambu", "host": "192.168.1.70"}
    assert [source["url"] for source in sources.values() if "url" in source] == ["rtsp://192.168.1.60/stream?token=[redacted]"]
    assert engine.printers.get(printer_id).name == "Renamed" and engine.printers.get(printer_id).config == SECRET_PRINTER
    assert engine.settings["catalogue_url"] == SECRET_CATALOGUE and engine.settings["mqtt"] == SECRET_MQTT
    assert engine.settings["notifiers"] == _secret_notifiers()[0]


async def test_a_blank_secret_is_kept_and_a_null_one_is_cleared() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id, _ = await _seed_secrets(engine)
        printer = engine.printers.get(printer_id)
        for blank in ({"base_url": SECRET_PRINTER["base_url"]}, {"base_url": "http://octopi.local", "api_key": ""}):
            await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": blank}})
            assert printer.config == SECRET_PRINTER
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "password": ""}, "notifiers": {"telegram": {"chat_id": "42"}}}})
        assert engine.settings["mqtt"] == {"host": "broker", "password": "mqtt-PASS-77b1e0"}
        assert engine.settings["notifiers"] == {"telegram": {"chat_id": "42", "bot_token": "telegram-bot_token-SECRET-5c3e"}}, "a required secret is met by the saved one"
        assert not _of(events, "error")

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://octopi.local", "api_key": None}}})
        assert printer.config == SECRET_PRINTER and "API key" in _of(events, "error")[-1]["message"], "a cleared secret the service needs is refused"
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://octopi.local"}}})
        assert printer.config == {"base_url": "http://octopi.local"}, "a secret was handed to a different service"
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "password": None}}})
        assert engine.settings["mqtt"] == {"host": "broker", "password": ""}
        state = engine.state_event()

    assert state["secrets_set"]["mqtt"] == [] and state["printers"][0]["secrets_set"] == []
    assert platform.state["settings"]["mqtt"] == {"host": "broker", "password": ""}


async def test_changing_a_printers_provider_keeps_none_of_its_old_config() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id, secrets = await _seed_secrets(engine)
        printer = engine.printers.get(printer_id)

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper"}})
        assert (printer.provider, printer.config) == ("octoprint", SECRET_PRINTER) and len(_of(events, "error")) == 1, "a switch with no config of its own is refused whole"

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://octopi.local", "api_key": "", "password": "typed-PASS-1d4e"}}})
        assert printer.config == SECRET_PRINTER, "a field the provider does not declare is not stored"

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "klipper", "config": {"base_url": "http://octopi.local"}}})
        assert (printer.provider, printer.config) == ("klipper", {"base_url": "http://octopi.local"})
        assert engine.state_event()["printers"][0]["secrets_set"] == []

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"provider": "octoprint"}})
        assert printer.provider == "klipper" and "api_key" not in printer.config, "switching back does not restore the key"
        assert not [secret for secret in ("PRINTERPASS-9d1", "octo-KEY-4f7a2c") if secret in json.dumps([engine.state_event(), events, platform.state])]


async def test_the_scrub_knows_every_services_secret_fields() -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, _):
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
        engine.printers.get(next(iter(engine.printers.items))).config = {"base_url": "http://op", "password": "left-PASS-1234", "api_key": "left-KEY-5678"}
        assert {"left-PASS-1234", "left-KEY-5678"} <= reports.collect_secrets(engine)


@pytest.mark.parametrize(
    ("private", "token"),
    [
        ("https://cat.example.com/tok_k9f8-a7s6_d5f4/catalogue.json", "tok_k9f8-a7s6_d5f4"),
        ("https://cat.example.com/k9f8a7s6/catalogue.json", "k9f8a7s6"),
        ("https://reader:CATPASS-6a0f@cat.example.com/acme-plugins/catalogue.json?token=cattok-3b7d", "acme-plugins"),
    ],
)
async def test_a_private_catalogues_whole_path_is_hidden(private: str, token: str) -> None:
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "settings.update", "patch": {"catalogue_url": private}})
        shown = engine.state_event()["settings"]["catalogue_url"]
        assert shown.startswith("https://cat.example.com/[redacted]") and token not in json.dumps([engine.state_event(), reports.diagnostics(engine)])
        assert token in reports.collect_secrets(engine) and token not in engine._scrubbed(f"fetching {private} failed")

        await engine.handle({"cmd": "settings.update", "patch": {"catalogue_url": shown}})
        assert engine.settings["catalogue_url"] == private, "the shown address is the stored one"

        await engine.handle({"cmd": "settings.update", "patch": {"catalogue_url": plugins.CATALOGUE_URL}})
        assert engine.state_event()["settings"]["catalogue_url"] == plugins.CATALOGUE_URL, "the public default is not hidden"


async def test_a_typed_connection_secret_reaches_only_the_tab_that_tested_it() -> None:
    platform = FakePlatform(infer_s=0.02)
    answer = platform.http

    async def quoting_what_it_was_sent(method: str, url: str, **kwargs):
        if "unreachable" in url or "telegram" in url:
            raise OSError(f"refused {url} with {kwargs.get('headers')}")
        return await answer(method, url, **kwargs)

    platform.http = quoting_what_it_was_sent
    async with running_engine(platform, camera_fps=[]) as (engine, other_tabs):
        asked: list[dict] = []
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "config": {"base_url": "http://unreachable", "api_key": "typed-KEY-93b1"}}, asked.append)
        await engine.handle({"cmd": "notify.test", "provider": "telegram", "config": {"chat_id": "9", "bot_token": "typed-BOT-93b1"}}, asked.append)

    results = _of(asked, "printer_test") + _of(asked, "notify_test")
    assert [event["ok"] for event in results] == [False, False] and all("refused" in event["error"] for event in results)
    assert _leaked(results, ["typed-KEY-93b1", "typed-BOT-93b1"]) == []
    assert not _of(other_tabs, "printer_test") and not _of(other_tabs, "notify_test")


async def test_a_login_the_deployment_holds_is_scrubbed_from_messages() -> None:
    platform = FakePlatform()
    platform.secrets = frozenset({"mtx-user", "MTX-PASS-77b1"})
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        engine.emit({"event": "warning", "message": "live view unavailable: rtsp://mtx-user:MTX-PASS-77b1@127.0.0.1:8554/cam1 refused", "recovered": False})
        assert _leaked([events, engine.recent_events(), reports.diagnostics(engine)], ["MTX-PASS-77b1"]) == []
        assert "MTX-PASS-77b1" not in "\n".join(logs.recent())


async def test_an_address_with_a_hidden_part_is_refused_and_an_unchanged_one_restored() -> None:
    stored = "http://octopi.local/hassio_ingress/AbCdEf0123456789AbCdEf/"
    async with running_engine(FakePlatform(), camera_fps=[]) as (engine, events):
        await engine.handle({"cmd": "printer.add", "printer": {"name": "P", "provider": "octoprint", "config": {"base_url": stored, "api_key": "k"}}})
        printer = engine.printers.get(next(iter(engine.printers.items)))
        shown = engine.state_event()["printers"][0]["config"]
        assert shown["base_url"] == "http://octopi.local/hassio_ingress/[redacted]/"

        await engine.handle({"cmd": "printer.update", "id": printer.id, "patch": {"config": shown}})
        assert printer.config["base_url"] == stored and not _of(events, "error")

        hidden = "http://elsewhere.local/hassio_ingress/[redacted]/"
        await engine.handle({"cmd": "printer.update", "id": printer.id, "patch": {"config": {"base_url": hidden, "api_key": "k"}}})
        await engine.handle({"cmd": "printer.add", "printer": {"name": "Q", "provider": "octoprint", "config": {"base_url": hidden, "api_key": "k"}}})
        await engine.handle({"cmd": "camera.add", "name": "c", "source": {"kind": "url", "url": "rtsp://cam.local/[redacted]"}})
        assert [event["message"] for event in _of(events, "error")] == ["the address has a hidden part, type it in full"] * 3
        assert printer.config["base_url"] == stored and len(engine.printers.values()) == 1 and not engine.cameras.values()


async def test_a_print_whose_file_is_gone_is_not_started_and_names_no_path() -> None:
    platform = FakePlatform()
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id = await _register_printer(engine)
        platform.device_status = "Operational"
        await platform.files.store("abcd1234.gcode", _chunks(b"G1 X1\n"))
        await engine.handle({"cmd": "print.add", "id": "abcd1234", "filename": "benchy.gcode", "printer_ids": [printer_id]})
        del platform.files.blobs["abcd1234.gcode"]
        await engine.handle({"cmd": "print.start", "id": "abcd1234", "printer_id": printer_id, "req_id": 1})

    assert [event["message"] for event in _of(events, "error")] == ["print 'abcd1234' has lost its file"]


async def test_typing_the_default_broker_port_is_not_a_changed_address() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        await _seed_secrets(engine)
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "port": 1883, "password": ""}}})

        assert not _of(events, "error")
        assert engine.settings["mqtt"] == {"host": "broker", "port": 1883, "password": "mqtt-PASS-77b1e0"}


@pytest.mark.parametrize(
    ("stored", "sent", "moved"),
    [
        ({}, {}, False),
        ({}, {"tls": True}, False),
        ({"tls": True}, {}, False),
        ({"tls": True}, {"tls": True, "port": 8883}, False),
        ({"tls": True}, {"tls": True, "port": 1883}, True),
        ({"tls": True}, {"port": 1883}, True),
        ({"tls": True}, {"port": 8883}, False),
        ({}, {"port": 1883}, False),
        ({}, {"port": 8883}, True),
        ({}, {"tls": True, "port": 8883}, True),
        ({"port": 1883}, {}, False),
        ({"tls": True, "port": 8883}, {"tls": True}, False),
        ({"tls": True, "port": 8883}, {}, True),
        ({"tls": True, "port": 8883}, {"tls": True, "port": 8884}, True),
        ({"port": 1884}, {}, True),
        ({"port": 1884}, {"port": 1884}, False),
        ({}, {"host": "elsewhere.example"}, True),
        ({}, {"base_url": "http://elsewhere.example"}, True),
        ({}, {"url": "https://elsewhere.example/topic"}, True),
    ],
)
def test_an_address_moves_with_its_host_url_or_the_port_actually_dialled(stored: dict, sent: dict, moved: bool) -> None:
    """A blank port is the one the broker's tls setting implies, and a tls switch with the port left blank is the same broker."""
    assert credentials.address_moved({"host": "broker.lan", **stored}, {"host": "broker.lan", **sent}) is moved


async def test_the_broker_password_is_kept_only_when_the_port_dialled_is_the_one_stored() -> None:
    platform = FakePlatform(infer_s=0.02)
    seeded = {"host": "broker.lan", "tls": True, "password": "broker-PASS-9"}
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        for patch in (
            {"tls": True, "port": 8883},
            {"tls": False},
            {"tls": True},
        ):
            await engine.handle({"cmd": "settings.update", "patch": {"mqtt": seeded}})
            await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker.lan", **patch, "password": ""}}})
            assert not _of(events, "error"), patch
            assert engine.settings["mqtt"]["password"] == "broker-PASS-9", patch
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": seeded}})
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"host": "broker.lan", "tls": True, "port": 1883, "password": ""}}})

    assert [event["message"] for event in _of(events, "error")] == [
        "send Password again, since a stored secret is only kept for the address it was saved with"
    ]
    assert "port" not in engine.settings["mqtt"], "a port other than the one in effect was saved with the stored password"


async def test_a_kept_secret_is_refused_for_an_address_that_changed() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id, secrets = await _seed_secrets(engine)
        notifiers = dict(engine.settings["notifiers"])
        moves = [
            {"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://elsewhere.example"}}},
            {"cmd": "settings.update", "patch": {"mqtt": {"host": "elsewhere.example"}}},
            {"cmd": "settings.update", "patch": {"mqtt": {"host": "broker", "port": 8883, "password": ""}}},
            {"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "https://elsewhere.example/topic"}}}},
        ]
        for move in moves:
            await engine.handle(move)
        refusals = [event["message"] for event in _of(events, "error")]
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": {"base_url": "http://elsewhere.example"}}, events.append)
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {"url": "https://elsewhere.example/topic"}}, events.append)
        sent_elsewhere = [request for request in platform.http_requests if "elsewhere" in request["url"]]
        untouched = (engine.printers.get(printer_id).config, engine.settings["mqtt"], engine.settings["notifiers"])

        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": {"base_url": "http://elsewhere.example", "api_key": "another"}}})
        moved = engine.printers.get(printer_id).config

    said = "again, since a stored secret is only kept for the address it was saved with"
    assert refusals == [f"send API key {said}", f"send Password {said}", f"send Password {said}", f"send Access token {said}"]
    assert [(test["ok"], test["error"]) for test in _of(events, "printer_test") + _of(events, "notify_test")] == [
        (False, f"send API key {said}"),
        (False, f"send Access token {said}"),
    ]
    assert not sent_elsewhere, "a stored secret was presented to an address it was not saved for"
    assert untouched == (SECRET_PRINTER, SECRET_MQTT, notifiers)
    assert moved == {"base_url": "http://elsewhere.example", "api_key": "another"}
    assert _leaked(events, secrets) == []


async def test_a_test_signs_in_with_the_stored_secret() -> None:
    platform = FakePlatform(infer_s=0.02)
    platform.device_status = "Operational"
    async with running_engine(platform, camera_fps=[]) as (engine, events):
        printer_id, _ = await _seed_secrets(engine)
        shown = engine.state_event()
        platform.http_requests.clear()
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": shown["printers"][0]["config"]}, events.append)
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "config": shown["printers"][0]["config"]}, events.append)
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {}}, events.append)
        await engine.handle({"cmd": "notify.test", "provider": "telegram", "config": {"chat_id": "9", "bot_token": "typed-token"}}, events.append)
        requests = list(platform.http_requests)

    assert [(test["ok"], test.get("error")) for test in _of(events, "printer_test")] == [(True, None), (False, "OctoPrint needs API key filled in")]
    assert [test["ok"] for test in _of(events, "notify_test")] == [True, True]
    tested = [request for request in requests if request["url"].startswith(SECRET_PRINTER["base_url"])]
    assert tested and all(request["headers"] == {"X-Api-Key": "octo-KEY-4f7a2c"} for request in tested)
    ntfy = next(request for request in requests if request["url"] == "https://hooks.example/ntfy-url-SECRET-5c3e")
    assert ntfy["headers"]["Authorization"] == "Bearer ntfy-token-SECRET-5c3e"
    assert any("typed-token" in request["url"] for request in requests), "a typed secret was replaced by the stored one"


async def test_a_printer_is_still_polled_with_its_key_after_an_update_that_left_it_blank(monkeypatch) -> None:
    monkeypatch.setattr(watchdog, "DEVICE_POLL_S", 0.05)
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[]) as (engine, _):
        printer_id, _ = await _seed_secrets(engine)
        shown = engine.state_event()["printers"][0]
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"name": "Renamed", "config": shown["config"]}})
        platform.http_requests.clear()
        await asyncio.sleep(0.3)
        polls = [request for request in platform.http_requests if "/api/job" in request["url"]]
        restarted = Engine(platform)
        await restarted.start()
        reloaded = restarted.printers.get(printer_id).config
        await restarted.stop()

    assert polls and all(poll["url"].startswith(SECRET_PRINTER["base_url"]) and poll["headers"] == {"X-Api-Key": "octo-KEY-4f7a2c"} for poll in polls)
    assert platform.state["printers"][0]["config"] == SECRET_PRINTER and reloaded == SECRET_PRINTER


async def test_a_plugin_granted_everything_is_shown_no_stored_secret() -> None:
    platform = FakePlatform(infer_s=0.02)
    async with running_engine(platform, camera_fps=[10.0]) as (engine, events):
        printer_id, secrets = await _seed_secrets(engine)
        shown = engine.state_event()["printers"][0]["config"]
        await engine.handle({"cmd": "printer.update", "id": printer_id, "patch": {"config": shown}})
        await engine.handle({"cmd": "printer.test", "provider": "octoprint", "id": printer_id, "config": shown}, events.append)
        await engine.handle({"cmd": "notify.test", "provider": "ntfy", "config": {}}, events.append)
        await asyncio.sleep(0.3)
        everything = list(plugins.PERMISSIONS)
        views = [plugins.project_state(engine.state_event(), everything), *(plugins.project_event(event, everything) for event in events)]

    assert any(view and view.get("event") == "state" for view in views)
    assert _leaked(views, secrets) == []
