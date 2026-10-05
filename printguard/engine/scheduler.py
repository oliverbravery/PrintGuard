"""Demand-driven inference scheduling with max-min fair rate allocation.

Capacity is never benchmarked up front: a smoothed estimate of observed
inference latency, a camera's own image adjustments included, continuously
yields the sustainable total rate, which is water-filled across cameras so no
camera is allocated beyond its effective rate (its native frame rate, held to
the cap its user set) and spare capacity flows to cameras that can use it.
Frames are grabbed at dispatch time and identified by sequence, so a frame is
never inferred twice and results always describe the present.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from . import logs, vision
from .platform import Frame, Platform
from .registry import Camera, CameraRegistry

logger = logging.getLogger(__name__)

LATENCY_SMOOTHING = 0.25
IDLE_POLL_S = 0.25
STALE_RETRY_S = 0.1
ERROR_THROTTLE_S = 30.0

ResultSink = Callable[[Camera, Frame, dict[str, Any]], Awaitable[None]]
ErrorSink = Callable[[str], None]


class Scheduler:
    """Allocates inference slots across registered cameras."""

    def __init__(self, platform: Platform, registry: CameraRegistry, on_result: ResultSink, on_error: ErrorSink) -> None:
        self._platform = platform
        self._registry = registry
        self._on_result = on_result
        self._on_error = on_error
        self._last_error_at = 0.0
        self._dispatch_lock = asyncio.Lock()
        self._jobs: set[asyncio.Task[None]] = set()
        self._camera_jobs: dict[str, asyncio.Task[None]] = {}
        self._slots = asyncio.Semaphore(platform.workers)
        self._job_finished = asyncio.Event()
        self.infer_ms = 0.0

    def reset(self) -> None:
        """Resets concurrency and latency after the inference runtime changes."""
        self._slots = asyncio.Semaphore(self._platform.workers)
        self.infer_ms = 0.0

    async def reconfigure(self, configure: Callable[[], Awaitable[None]]) -> None:
        """Drains active work and applies a new inference configuration."""
        async with self._dispatch_lock:
            if self._jobs:
                await asyncio.gather(*self._jobs)
            await configure()
            self.reset()

    def capacity_fps(self) -> float:
        """Total sustainable inferences per second given observed latency."""
        if self.infer_ms <= 0:
            return 0.0
        return self._platform.workers * 1000.0 / self.infer_ms

    def stats(self) -> dict[str, Any]:
        """Live scheduler statistics for the state event."""
        return {
            "inference_device": self._platform.inference_device,
            "infer_ms": round(self.infer_ms, 1),
            "capacity_fps": round(self.capacity_fps(), 2),
        }

    def allocate(self) -> None:
        """Water-fills capacity into per-camera target rates.

        Cameras are visited in ascending order of effective rate; each takes
        the smaller of its effective rate and an equal share of what remains,
        releasing any surplus to faster cameras. Until the first latency
        observation exists, targets fall back to effective rates and
        the worker semaphore alone provides backpressure.
        """
        cameras = self._registry.schedulable()
        if not cameras:
            return
        remaining = self.capacity_fps()
        if remaining <= 0:
            for camera in cameras:
                camera.target_fps = camera.effective_fps
            return
        for index, camera in enumerate(sorted(cameras, key=lambda c: c.effective_fps)):
            share = remaining / (len(cameras) - index)
            camera.target_fps = min(camera.effective_fps, share)
            remaining -= camera.target_fps

    def cancel_camera(self, camera: Camera) -> None:
        """Cancels the active inference job for a restarted camera."""
        if task := self._camera_jobs.get(camera.id):
            task.cancel()

    async def dispatch(self) -> float:
        """Hands the most overdue camera to a free worker, or waits for one to fall due.

        A camera can be dispatched again once its interval has passed and its
        last inference has come back. Only the first has a known time, so a
        pass that finds nothing due sleeps until the earliest idle camera's
        interval is up or any inference finishes, whichever comes first.
        Sleeping on the idle cameras alone would hold a fast camera that is
        mid-inference to the pace of a slow one beside it.

        Returns:
            Seconds until another pass is worth making, which is always none.
        """
        async with self._dispatch_lock:
            self._job_finished.clear()
            self.allocate()
            now = time.monotonic()
            idle = [c for c in self._registry.schedulable() if not c.inferring]
            due = [c for c in idle if now >= c.next_due]
            if due:
                camera = min(due, key=lambda c: c.next_due)
                await self._slots.acquire()
                camera.inferring = True
                camera.next_due = time.monotonic() + 1.0 / max(0.1, camera.target_fps or camera.effective_fps)
                task = asyncio.create_task(self._job(camera))
                self._jobs.add(task)
                task.add_done_callback(self._jobs.discard)
                self._camera_jobs[camera.id] = task

                def forget(done: asyncio.Task[None]) -> None:
                    if self._camera_jobs.get(camera.id) is done:
                        self._camera_jobs.pop(camera.id)

                task.add_done_callback(forget)
                return 0.0
            wait = min((c.next_due - now for c in idle), default=IDLE_POLL_S)
        try:
            async with asyncio.timeout(min(wait, IDLE_POLL_S)):
                await self._job_finished.wait()
        except TimeoutError:
            pass
        return 0.0

    async def _job(self, camera: Camera) -> None:
        try:
            frame = await camera.frame_source.grab() if camera.frame_source else None
            if frame is None or frame.seq == camera.last_seq:
                camera.next_due = time.monotonic() + STALE_RETRY_S
                return
            camera.last_seq = frame.seq
            started = time.monotonic()
            rgb = await asyncio.to_thread(
                vision.transform,
                frame.rgb,
                rotation=camera.rotation,
                crop=camera.crop,
                brightness=camera.brightness,
                contrast=camera.contrast,
                sharpness=camera.sharpness,
            )
            result = await self._platform.infer(rgb)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self.infer_ms = (
                elapsed_ms
                if not self.infer_ms
                else (1 - LATENCY_SMOOTHING) * self.infer_ms + LATENCY_SMOOTHING * elapsed_ms
            )
            camera.mark_inferred(result)
            await self._on_result(camera, Frame(rgb=rgb, seq=frame.seq, ts=frame.ts), result)
        except Exception as exc:
            camera.next_due = time.monotonic() + STALE_RETRY_S
            logger.debug("inference failed on '%s'", camera.name, exc_info=True)
            if time.monotonic() - self._last_error_at > ERROR_THROTTLE_S:
                self._last_error_at = time.monotonic()
                self._on_error(f"inference failed on '{camera.name}': {logs.describe(exc)}")
        finally:
            camera.inferring = False
            self._slots.release()
            self._job_finished.set()
