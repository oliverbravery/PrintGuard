"""Demand-driven inference scheduling with max-min fair rate allocation.

Capacity is never benchmarked up front: a smoothed estimate of observed
inference latency continuously yields the sustainable total rate, which is
water-filled across cameras so no camera is allocated beyond its native
frame rate and spare capacity flows to cameras that can use it. Frames are
grabbed at dispatch time and identified by sequence, so a frame is never
inferred twice and results always describe the present.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .platform import Frame, Platform
from .registry import Camera, CameraRegistry

LATENCY_SMOOTHING = 0.25
IDLE_POLL_S = 0.05
STALE_RETRY_S = 0.1

ResultSink = Callable[[Camera, Frame, dict[str, Any]], Awaitable[None]]


class Scheduler:
    """Allocates inference slots across registered cameras."""

    def __init__(self, platform: Platform, registry: CameraRegistry, on_result: ResultSink) -> None:
        self._platform = platform
        self._registry = registry
        self._on_result = on_result
        self._slots = asyncio.Semaphore(platform.workers)
        self.infer_ms = 0.0

    def capacity_fps(self) -> float:
        """Total sustainable inferences per second given observed latency."""
        if self.infer_ms <= 0:
            return 0.0
        return self._platform.workers * 1000.0 / self.infer_ms

    def stats(self) -> dict[str, Any]:
        """Live scheduler statistics for the state event."""
        return {
            "workers": self._platform.workers,
            "infer_ms": round(self.infer_ms, 1),
            "capacity_fps": round(self.capacity_fps(), 2),
        }

    def allocate(self) -> None:
        """Water-fills capacity into per-camera target rates.

        Cameras are visited in ascending order of native frame rate; each
        takes the smaller of its native rate and an equal share of what
        remains, releasing any surplus to faster cameras. Until the first
        latency observation exists, targets fall back to native rates and
        the worker semaphore alone provides backpressure.
        """
        cameras = self._registry.schedulable()
        if not cameras:
            return
        remaining = self.capacity_fps()
        if remaining <= 0:
            for camera in cameras:
                camera.target_fps = camera.max_fps
            return
        for index, camera in enumerate(sorted(cameras, key=lambda c: c.max_fps)):
            share = remaining / (len(cameras) - index)
            camera.target_fps = min(camera.max_fps, share)
            remaining -= camera.target_fps

    async def run(self) -> None:
        """Dispatch loop: hands the most overdue camera to a free worker."""
        while True:
            self.allocate()
            now = time.monotonic()
            due = [c for c in self._registry.schedulable() if not c.inferring and now >= c.next_due]
            if not due:
                await asyncio.sleep(self._sleep_until_due(now))
                continue
            camera = min(due, key=lambda c: c.next_due)
            await self._slots.acquire()
            camera.inferring = True
            camera.next_due = time.monotonic() + 1.0 / max(0.1, camera.target_fps or camera.max_fps)
            asyncio.ensure_future(self._job(camera))

    def _sleep_until_due(self, now: float) -> float:
        pending = [c.next_due - now for c in self._registry.schedulable() if not c.inferring]
        if not pending:
            return IDLE_POLL_S
        return min(max(min(pending), 0.005), 0.25)

    async def _job(self, camera: Camera) -> None:
        try:
            frame = await camera.frame_source.grab() if camera.frame_source else None
            if frame is None or frame.seq == camera.last_seq:
                camera.next_due = time.monotonic() + STALE_RETRY_S
                return
            camera.last_seq = frame.seq
            started = time.monotonic()
            result = await self._platform.infer(frame.rgb)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self.infer_ms = (
                elapsed_ms
                if not self.infer_ms
                else (1 - LATENCY_SMOOTHING) * self.infer_ms + LATENCY_SMOOTHING * elapsed_ms
            )
            camera.mark_inferred(result)
            await self._on_result(camera, frame, result)
        finally:
            camera.inferring = False
            self._slots.release()
