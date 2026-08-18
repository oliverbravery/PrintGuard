"""The complete contract between the shared engine and a runtime platform.

Hub mode and local mode differ only in the implementations of these
protocols; everything that consumes them is shared code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

import numpy as np

if TYPE_CHECKING:
    from .registry import Plugin


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
    standby: bool

    async def grab(self) -> Frame | None:
        """Returns the freshest available frame, or None if not ready."""
        ...

    def set_monitoring(self, active: bool) -> None:
        """Starts or stops capture needed by inference."""
        ...

    def close(self) -> None:
        """Releases the underlying capture resources."""
        ...


class PluginRuntime(Protocol):
    """Sandbox that runs the background half of installed plugins.

    Only the hub has one. In local mode the browser runs the same source in
    the same sandbox the UI half uses, so ``Platform.plugin_runtime`` is None
    there and the engine simply has nothing to drive.
    """

    def attach(self, request: Callable[..., Awaitable[Any]], failed: Callable[[str, str], None]) -> None:
        """Gives the runtime the engine's command channel and failure report."""
        ...

    def on_event(self, event: dict[str, Any]) -> None:
        """Accepts an engine event for delivery to the running plugins."""
        ...

    async def reload(self, running: "list[Plugin]") -> None:
        """Replaces the running set, starting and stopping sandboxes to match."""
        ...

    async def serve(self, plugin_id: str, request: dict[str, Any]) -> dict[str, Any] | None:
        """Answers a request to a plugin's own routes, or None if it has none."""
        ...

    async def authorise(self, request: dict[str, Any]) -> bool | None:
        """Asks any gating plugin to allow a request, returning None when none gates."""
        ...

    def gate_paths(self) -> tuple[str, ...]:
        """Returns the route prefixes a gating plugin's own pages are served on."""
        ...

    async def close(self) -> None:
        """Tears every sandbox down."""
        ...


class Platform(Protocol):
    """Runtime services the engine needs but cannot implement portably."""

    mode: str
    host: str
    """Which deployment this is, one of ``plugins.PLATFORMS``. A plugin declares
    the ones it runs on, and the store offers what matches."""

    workers: int
    inference_device: str
    version: str
    update_repo: str | None
    """GitHub ``owner/name`` to check for updates, or None to never call out
    (local mode is always the latest deployed build)."""

    update_asset: str | None
    """Release asset filename this deployment updates with (the desktop app's
    installer), or None when the deployment updates outside the app."""

    plugin_runtime: PluginRuntime | None
    """Sandbox for the background half of plugins, or None where the runtime
    lives outside the engine (the browser runs it in its own sandbox)."""

    async def configure(self, settings: dict[str, Any]) -> None:
        """Applies platform-owned settings before inference starts."""
        ...

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
        binary: bool = False,
        timeout: float = 10.0,
    ) -> tuple[int, Any]:
        """Performs an HTTP request and returns (status, parsed body)."""
        ...

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        """Encodes an RGB frame as JPEG for alert snapshots."""
        ...

    async def decode_jpeg(self, data: bytes) -> np.ndarray | None:
        """Decodes image bytes to an HxWx3 RGB frame, or None if undecodable."""
        ...

    def load_state(self) -> dict[str, Any]:
        """Loads the persisted engine state, or an empty dict."""
        ...

    def save_state(self, state: dict[str, Any]) -> None:
        """Persists the engine state."""
        ...
