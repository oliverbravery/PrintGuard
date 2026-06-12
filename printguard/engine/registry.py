"""Camera registry: identity, access details and live per-camera stats."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .cameras import CAMERA_DEFAULTS
from .platform import FrameSource
from .printers import printer_watching


@dataclass
class Camera:
    """A registered camera and its runtime statistics.

    Attributes:
        id: Stable identifier used across the protocol and as the MediaMTX
            path name in hub mode.
        name: Display name.
        source: Access details — {"kind": "device", "device_id": ...} in
            local mode, {"kind": "url" | "path", ...} in hub mode.
        max_fps: Native frame rate measured when the camera was registered.
        target_fps: Inference rate currently allocated by the scheduler.
        achieved_fps: Smoothed rate of completed inferences.
        inferring: Whether an inference on this camera is in flight.
        in_use: Whether an enabled printer is bound to this camera.
        online: Whether the frame source is currently delivering frames.
    """

    id: str
    name: str
    source: dict[str, Any]
    max_fps: float
    brightness: float = CAMERA_DEFAULTS["brightness"]
    contrast: float = CAMERA_DEFAULTS["contrast"]
    sharpness: float = CAMERA_DEFAULTS["sharpness"]
    crop: dict[str, float] | None = CAMERA_DEFAULTS["crop"]
    target_fps: float = 0.0
    achieved_fps: float = 0.0
    inferring: bool = False
    in_use: bool = False
    last_seq: float = -1.0
    next_due: float = 0.0
    last_done: float = 0.0
    last_result: dict[str, Any] | None = None
    frame_source: FrameSource | None = field(default=None, repr=False)

    @property
    def online(self) -> bool:
        """Whether the camera's frame source is attached and healthy."""
        return self.frame_source is not None and self.frame_source.online

    def mark_inferred(self, result: dict[str, Any]) -> None:
        """Records a completed inference and updates the achieved rate."""
        now = time.monotonic()
        if self.last_done:
            inst = 1.0 / max(1e-6, now - self.last_done)
            self.achieved_fps = inst if not self.achieved_fps else 0.75 * self.achieved_fps + 0.25 * inst
        self.last_done = now
        self.last_result = result

    def public(self) -> dict[str, Any]:
        """Serialises the camera with live stats for the state event."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "max_fps": round(self.max_fps, 2),
            "target_fps": round(self.target_fps, 2),
            "achieved_fps": round(self.achieved_fps, 2),
            "inferring": self.inferring,
            "in_use": self.in_use,
            "online": self.online,
            "last_result": self.last_result,
            "brightness": round(self.brightness, 2),
            "contrast": round(self.contrast, 2),
            "sharpness": round(self.sharpness, 2),
            "crop": self.crop,
        }

    def persisted(self) -> dict[str, Any]:
        """Serialises only what is needed to restore the camera on boot."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "max_fps": self.max_fps,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "sharpness": self.sharpness,
            "crop": self.crop,
        }


class CameraRegistry:
    """Holds all registered cameras keyed by id."""

    def __init__(self) -> None:
        self.cameras: dict[str, Camera] = {}

    def add(self, camera: Camera) -> None:
        """Registers a camera."""
        self.cameras[camera.id] = camera

    def remove(self, camera_id: str) -> Camera | None:
        """Deregisters a camera, closing its frame source.

        Args:
            camera_id: Identifier of the camera to remove.

        Returns:
            The removed camera, or None if it was not registered.
        """
        camera = self.cameras.pop(camera_id, None)
        if camera and camera.frame_source:
            camera.frame_source.close()
            camera.frame_source = None
        return camera

    def get(self, camera_id: str) -> Camera | None:
        """Looks up a camera by id."""
        return self.cameras.get(camera_id)

    def schedulable(self) -> list[Camera]:
        """Cameras eligible for inference: in use, online and attached."""
        return [c for c in self.cameras.values() if c.in_use and c.online]

    def sync_in_use(self, printers: dict[str, dict[str, Any]]) -> None:
        """Recomputes in_use flags from the printers currently watched."""
        bound = {p["camera_id"] for p in printers.values() if printer_watching(p)}
        for camera in self.cameras.values():
            camera.in_use = camera.id in bound
