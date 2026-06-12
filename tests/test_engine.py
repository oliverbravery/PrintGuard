"""Engine simulation: fairness, frame dedup and the defect pipeline.

Run directly: uv run python tests/test_engine.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np

from printguard.engine import monitor
from printguard.engine.engine import Engine
from printguard.engine.platform import Frame


class FakeSource:
    """Synthetic camera producing frames at a fixed rate."""

    def __init__(self, fps: float) -> None:
        self.fps = fps
        self.online = True
        self._born = time.monotonic()

    async def grab(self) -> Frame | None:
        seq = int((time.monotonic() - self._born) * self.fps)
        rgb = np.full((48, 64, 3), seq % 255, dtype=np.uint8)
        return Frame(rgb=rgb, seq=float(seq), ts=time.time())

    def close(self) -> None:
        self.online = False


class FakePlatform:
    """In-memory platform with deterministic latency and HTTP."""

    mode = "test"
    workers = 1

    def __init__(self, infer_s: float = 0.05, failing: bool = False) -> None:
        self.infer_s = infer_s
        self.failing = failing
        self.device_status = "Printing"
        self.reject_actions = False
        self.http_calls: list[tuple[str, str]] = []
        self.state: dict[str, Any] = {}

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        await asyncio.sleep(self.infer_s)
        distances = {"success": 9.0, "failure": 1.0} if self.failing else {"success": 1.0, "failure": 9.0}
        return {"prediction": "failure" if self.failing else "success", "distances": distances, "margin": 8.0}

    async def discover_cameras(self) -> list[dict[str, Any]]:
        return []

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> FakeSource:
        return FakeSource(float(source["fps"]))

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        pass

    async def http(self, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        self.http_calls.append((method, url))
        if self.reject_actions and method == "POST" and "/api/job" in url:
            raise RuntimeError("printer refused")
        return 200, {"state": self.device_status, "progress": {"completion": 40.0}, "job": {"file": {"name": "benchy.gcode"}}}

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        return b"\xff\xd8fake"

    def load_state(self) -> dict[str, Any]:
        return self.state

    def save_state(self, state: dict[str, Any]) -> None:
        self.state = state


async def setup_engine(platform: FakePlatform, camera_fps: list[float]) -> tuple[Engine, list[dict]]:
    engine = Engine(platform)
    events: list[dict] = []
    await engine.start()
    engine.add_sink(events.append)
    for fps in camera_fps:
        await engine.handle({"cmd": "camera.add", "name": f"cam{fps}", "source": {"kind": "fake", "fps": fps}})
    for camera in engine.registry.cameras.values():
        await engine.handle({"cmd": "printer.add", "printer": {"name": f"p-{camera.name}", "camera_id": camera.id}})
    return engine, events


async def test_fair_allocation_and_dedup() -> None:
    platform = FakePlatform(infer_s=0.05)
    engine, events = await setup_engine(platform, camera_fps=[30.0, 10.0, 3.0])
    seen: dict[str, list[float]] = {}
    original = engine.scheduler._on_result

    async def spy(camera, frame, result):
        seen.setdefault(camera.id, []).append(frame.seq)
        await original(camera, frame, result)

    engine.scheduler._on_result = spy
    await asyncio.sleep(5.0)
    names = {cid: camera.name for cid, camera in engine.registry.cameras.items()}
    await engine.stop()

    capacity = engine.scheduler.capacity_fps()
    assert 14.0 < capacity < 26.0, f"capacity estimate off: {capacity}"
    by_name = {names[cid]: seqs for cid, seqs in seen.items()}
    for seqs in seen.values():
        assert seqs == sorted(set(seqs)), "a frame was inferred twice or out of order"
    slow_rate = len(by_name["cam3.0"]) / 5.0
    fast_rate = len(by_name["cam30.0"]) / 5.0
    mid_rate = len(by_name["cam10.0"]) / 5.0
    assert 2.0 <= slow_rate <= 3.5, f"slow camera should run near native rate, got {slow_rate}"
    assert fast_rate > slow_rate, "surplus capacity should flow to the fast camera"
    assert abs(fast_rate - mid_rate) < 3.5, f"fast/mid should share fairly: {fast_rate} vs {mid_rate}"
    print(f"ok fairness: capacity={capacity:.1f}fps rates fast={fast_rate:.1f} mid={mid_rate:.1f} slow={slow_rate:.1f}")


async def test_defect_pipeline() -> None:
    platform = FakePlatform(infer_s=0.02, failing=True)
    engine, events = await setup_engine(platform, camera_fps=[10.0])
    printer_id = next(iter(engine.printers))
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
    await engine.handle(
        {
            "cmd": "printer.update",
            "id": printer_id,
            "patch": {
                "notify": True,
                "device": {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}, "on_defect": "pause"},
            },
        }
    )
    await asyncio.sleep(2.0)
    await engine.stop()

    alerts = [e for e in events if e.get("event") == "alert"]
    assert alerts, "no alert emitted for sustained defect"
    assert alerts[0]["action"] == "pause", f"expected pause action, got {alerts[0]}"
    assert any("/api/job" in url for _, url in platform.http_calls), "OctoPrint pause was never sent"
    results = [e for e in events if e.get("event") == "result"]
    assert results and all(r["prediction"] == "failure" for r in results)
    assert engine.state_event()["printers"][0]["alert"], "alert missing from state"
    assert ("PUT", "http://ntfy/topic") in platform.http_calls, "ntfy alert was never delivered"
    assert any("api.telegram.org" in url and url.endswith("/sendPhoto") for _, url in platform.http_calls), "Telegram alert was never delivered"
    assert ("POST", "http://disc/hook") in platform.http_calls, "Discord alert was never delivered"
    print(f"ok defect pipeline: {len(results)} results, alert score={alerts[0]['score']}, action=pause, 3 notifiers delivered")


async def test_standby_gating() -> None:
    monitor.DEVICE_POLL_S = 0.1
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.device_status = "Operational"
    engine, events = await setup_engine(platform, camera_fps=[10.0])
    printer_id = next(iter(engine.printers))
    await engine.handle(
        {
            "cmd": "printer.update",
            "id": printer_id,
            "patch": {"device": {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}},
        }
    )
    await asyncio.sleep(1.0)
    assert not engine.state_event()["printers"][0]["watching"], "idle printer should be in standby"
    assert not engine.registry.schedulable(), "standby printer's camera should not be scheduled"
    results_during_standby = len([e for e in events if e.get("event") == "result"])

    platform.device_status = "Printing"
    await asyncio.sleep(1.0)
    assert engine.state_event()["printers"][0]["watching"], "printing printer should be watched"
    resumed = len([e for e in events if e.get("event") == "result"]) - results_during_standby
    await engine.stop()
    assert resumed > 0, "inference did not resume when printing started"
    print(f"ok standby gating: 0 results while idle, {resumed} after printing resumed")


async def test_watchdog_and_failed_action() -> None:
    monitor.DEVICE_POLL_S = 0.1
    monitor.WATCH_TICK_S = 0.05
    monitor.OFFLINE_GRACE_S = 0.2
    monitor.ACT_RETRY_S = 0.01
    platform = FakePlatform(infer_s=0.02, failing=True)
    platform.reject_actions = True
    engine, events = await setup_engine(platform, camera_fps=[10.0])
    printer_id = next(iter(engine.printers))
    await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"ntfy": {"url": "http://ntfy/topic"}}}})
    await engine.handle(
        {
            "cmd": "printer.update",
            "id": printer_id,
            "patch": {
                "notify": True,
                "device": {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}, "on_defect": "pause"},
            },
        }
    )
    await asyncio.sleep(1.0)
    alerts = [e for e in events if e.get("event") == "alert"]
    assert alerts and alerts[0]["action"] == "failed", f"rejected pause should surface as failed, got {alerts}"
    errors = [e for e in events if e.get("event") == "error"]
    assert any("pause failed" in e["message"] for e in errors), "failed action did not emit an error event"

    camera = next(iter(engine.registry.cameras.values()))
    camera.frame_source.online = False
    await asyncio.sleep(0.6)
    warnings = [e for e in events if e.get("event") == "warning" and not e["recovered"]]
    assert any("offline" in w["message"] for w in warnings), "camera outage did not warn"
    assert any(url == "http://ntfy/topic" for _, url in platform.http_calls), "outage warning was not pushed to notifiers"

    camera.frame_source.online = True
    await asyncio.sleep(0.3)
    await engine.stop()
    recoveries = [e for e in events if e.get("event") == "warning" and e["recovered"]]
    assert any("back" in r["message"] for r in recoveries), "camera recovery was not announced"
    print(f"ok watchdog: failed action surfaced, {len(warnings)} warnings, recovery announced")


async def main() -> None:
    await test_fair_allocation_and_dedup()
    await test_defect_pipeline()
    await test_standby_gating()
    await test_watchdog_and_failed_action()
    print("all engine tests passed")


if __name__ == "__main__":
    asyncio.run(main())
