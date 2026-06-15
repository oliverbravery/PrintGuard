"""The complete contract between the shared engine and a runtime platform.

Hub mode and local mode differ only in the implementations of these
protocols; everything that consumes them is shared code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass
class Frame:
    """A single captured video frame.

    Attributes:
        rgb: HxWx3 uint8 frame in RGB channel order.
        seq: Monotonic identity of the frame; equal seq means equal frame,
            which the scheduler uses to never infer the same frame twice.
        ts: Capture wall-clock time in seconds.
    """

    rgb: np.ndarray
    seq: float
    ts: float


class FrameSource(Protocol):
    """Live handle onto a registered camera."""

    fps: float
    online: bool

    async def grab(self) -> Frame | None:
        """Returns the freshest available frame, or None if not ready."""
        ...

    def close(self) -> None:
        """Releases the underlying capture resources."""
        ...


class Platform(Protocol):
    """Runtime services the engine needs but cannot implement portably."""

    mode: str
    workers: int

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        """Runs the model on an RGB frame and returns a classify() result."""
        ...

    async def discover_cameras(self) -> list[dict[str, Any]]:
        """Lists attachable camera sources not yet registered."""
        ...

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> FrameSource:
        """Opens a frame source for a registered camera, measuring its fps."""
        ...

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        """Tears down any external resources created for a camera."""
        ...

    async def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, Any]:
        """Performs an HTTP request and returns (status, parsed body)."""
        ...

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        """Encodes an RGB frame as JPEG for alert snapshots."""
        ...

    def load_state(self) -> dict[str, Any]:
        """Loads the persisted engine state, or an empty dict."""
        ...

    def save_state(self, state: dict[str, Any]) -> None:
        """Persists the engine state."""
        ...
