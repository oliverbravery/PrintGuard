"""In-memory platform and frame source shared across the engine tests."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

import numpy as np

from printguard.engine.platform import Frame


class FakeSource:
    """Synthetic camera producing frames at a fixed rate."""

    def __init__(self, fps: float) -> None:
        self.fps = fps
        self.online = True
        self.standby = False
        self.frozen = False
        self._born = time.monotonic()

    async def grab(self) -> Frame | None:
        seq = 0 if self.frozen else int((time.monotonic() - self._born) * self.fps)
        rgb = np.full((48, 64, 3), seq % 255, dtype=np.uint8)
        return Frame(rgb=rgb, seq=float(seq), ts=time.time())

    def set_monitoring(self, active: bool) -> None:
        self.standby = not active
        self.online = active

    def close(self) -> None:
        self.online = False


class FakePlatform:
    """In-memory platform with deterministic latency and HTTP."""

    mode = "test"
    workers = 1
    inference_device = "test"
    version = "2.1.0"
    update_repo: str | None = None
    update_asset: str | None = None

    def __init__(self, infer_s: float = 0.05, failing: bool = False) -> None:
        self.infer_s = infer_s
        self.failing = failing
        self.device_status = "Printing"
        self.reject_actions = False
        self.action_delay_s = 0.0
        self.action_started = asyncio.Event()
        self.report_status = 200
        self.http_calls: list[tuple[str, str]] = []
        self.http_requests: list[dict[str, Any]] = []
        self.releases: list[dict[str, Any]] = []
        self.released_cameras: list[str] = []
        self.state: dict[str, Any] = {}
        self.inference_runtime = "auto"

    async def configure(self, settings: dict[str, Any]) -> None:
        """Records the selected inference runtime."""
        self.inference_runtime = settings["inference_runtime"]

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        await asyncio.sleep(self.infer_s)
        distances = {"success": 9.0, "failure": 1.0} if self.failing else {"success": 1.0, "failure": 9.0}
        return {"prediction": "failure" if self.failing else "success", "distances": distances, "margin": 8.0}

    async def discover_cameras(self) -> list[dict[str, Any]]:
        return []

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> FakeSource:
        return FakeSource(float(source.get("fps", 15.0)))

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        self.released_cameras.append(camera_id)

    async def http(self, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        self.http_calls.append((method, url))
        self.http_requests.append({"method": method, "url": url, **kwargs})
        hostname = urlparse(url).hostname or ""
        if hostname == "api.github.com":
            return 200, self.releases
        if hostname == "sentry.io" or hostname.endswith(".sentry.io"):
            return self.report_status, {}
        if method == "POST" and "/api/job" in url:
            self.action_started.set()
            await asyncio.sleep(self.action_delay_s)
        if self.reject_actions and method == "POST" and "/api/job" in url:
            raise RuntimeError("printer refused")
        return 200, {"state": self.device_status, "progress": {"completion": 40.0}, "job": {"file": {"name": "benchy.gcode"}}}

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        return b"\xff\xd8fake"

    async def decode_jpeg(self, data: bytes) -> np.ndarray | None:
        return np.zeros((48, 64, 3), dtype=np.uint8) if data.startswith(b"\xff\xd8") else None

    def load_state(self) -> dict[str, Any]:
        return self.state

    def save_state(self, state: dict[str, Any]) -> None:
        self.state = state
