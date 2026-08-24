"""Resource registries - cameras, integrated printers, API tokens and installed
plugins - each an id-keyed collection of records carrying identity, access
details and any live runtime state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from .cameras import CAMERA_DEFAULTS
from .monitors import monitor_watching
from .platform import FrameSource

logger = logging.getLogger(__name__)


class _Identified(Protocol):
    id: str


T = TypeVar("T", bound=_Identified)


class Registry(Generic[T]):
    """An id-keyed collection of registered resources."""

    def __init__(self) -> None:
        self.items: dict[str, T] = {}

    def add(self, item: T) -> None:
        """Registers a resource."""
        self.items[item.id] = item
        logger.info("%s %s registered", type(item).__name__.lower(), item.id)

    def get(self, item_id: str) -> T | None:
        """Looks up a resource by id."""
        return self.items.get(item_id)

    def remove(self, item_id: str) -> T | None:
        """Deregisters a resource, returning it or None if absent."""
        item = self.items.pop(item_id, None)
        if item is not None:
            logger.info("%s %s removed", type(item).__name__.lower(), item_id)
        return item

    def values(self) -> list[T]:
        """All registered resources."""
        return list(self.items.values())


@dataclass
class Camera:
    """A registered camera and its runtime statistics.

    Attributes:
        id: Stable identifier used across the protocol and as the MediaMTX
            path name in hub mode.
        name: Display name.
        source: Access details - {"kind": "device", "device_id": ...} in
            local mode, {"kind": "url" | "path", ...} in hub mode.
        printer_id: Owning printer when the camera was exposed by a printer
            integration, else None. Such cameras are managed by their printer:
            they cannot be removed on their own and are dropped with it.
        max_fps: Native frame rate measured when the camera was registered.
        target_fps: Inference rate currently allocated by the scheduler.
        achieved_fps: Smoothed rate of completed inferences.
        inferring: Whether an inference on this camera is in flight.
        in_use: Whether an enabled monitor is bound to this camera.
        online: Whether the frame source is currently delivering frames.
    """

    id: str
    name: str
    source: dict[str, Any]
    max_fps: float
    printer_id: str | None = None
    brightness: float = CAMERA_DEFAULTS["brightness"]
    contrast: float = CAMERA_DEFAULTS["contrast"]
    sharpness: float = CAMERA_DEFAULTS["sharpness"]
    crop: dict[str, float] | None = CAMERA_DEFAULTS["crop"]
    rotation: int = CAMERA_DEFAULTS["rotation"]
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

    @property
    def standby(self) -> bool:
        """Whether capture is intentionally sleeping until it is needed."""
        return self.frame_source is not None and self.frame_source.standby

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
            "printer_id": self.printer_id,
            "max_fps": round(self.max_fps, 2),
            "target_fps": round(self.target_fps, 2),
            "achieved_fps": round(self.achieved_fps, 2),
            "inferring": self.inferring,
            "in_use": self.in_use,
            "online": self.online,
            "standby": self.standby,
            "last_result": self.last_result,
            "brightness": round(self.brightness, 2),
            "contrast": round(self.contrast, 2),
            "sharpness": round(self.sharpness, 2),
            "crop": self.crop,
            "rotation": self.rotation,
        }

    def persisted(self) -> dict[str, Any]:
        """Serialises only what is needed to restore the camera on boot."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "printer_id": self.printer_id,
            "max_fps": self.max_fps,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "sharpness": self.sharpness,
            "crop": self.crop,
            "rotation": self.rotation,
        }


@dataclass
class Printer:
    """A registered integrated printer and its last polled state.

    Attributes:
        id: Stable identifier used across the protocol.
        name: Display name.
        provider: Integration adapter id (octoprint, klipper, elegoo, prusa, bambu, …).
        config: Connection values matching the adapter's schema.
        device_state: Last normalised state polled from the service, or None.
    """

    id: str
    name: str
    provider: str
    config: dict[str, Any]
    device_state: dict[str, Any] | None = None

    @property
    def online(self) -> bool:
        """Whether the service last reported a reachable state."""
        return bool(self.device_state) and self.device_state["status"] not in ("offline", "unknown")

    def public(self) -> dict[str, Any]:
        """Serialises the printer with its live state for the state event."""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "config": self.config,
            "device_state": self.device_state,
            "online": self.online,
        }

    def persisted(self) -> dict[str, Any]:
        """Serialises only what is needed to restore the printer on boot."""
        return {"id": self.id, "name": self.name, "provider": self.provider, "config": self.config}


@dataclass
class Token:
    """A scoped bearer token gating the hub's REST and MCP transports.

    Only the secret's hash is retained; the secret itself is surfaced once at
    creation and is unrecoverable thereafter.

    Attributes:
        id: Stable identifier used to name and revoke the token.
        name: Display name.
        scope: Granted capability - one of read, control or manage.
        hash: SHA-256 of the bearer secret, matched at auth time.
        hint: Short non-secret prefix shown in the UI.
        created: Unix timestamp the token was minted.
    """

    id: str
    name: str
    scope: str
    hash: str
    hint: str
    created: float

    def public(self) -> dict[str, Any]:
        """Serialises the token without its secret hash for the state event."""
        return {"id": self.id, "name": self.name, "scope": self.scope, "hint": self.hint, "created": self.created}

    def persisted(self) -> dict[str, Any]:
        """Serialises the token, hash included, to restore it on boot."""
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "hash": self.hash,
            "hint": self.hint,
            "created": self.created,
        }


@dataclass
class Plugin:
    """An installed plugin, where it came from, what it may do, and its code.

    Attributes:
        id: The manifest's plugin id, unique across installed plugins.
        manifest: The validated manifest, carrying the permissions the plugin
            asks for and the surfaces it draws on.
        sources: Plugin source files keyed by filename. Held here rather than
            re-fetched so an installed plugin keeps working offline and the
            bytes stay the ones that were hashed at install.
        assets: The files the plugin ships beside its code, base64 encoded and
            keyed by name, held for the same reason.
        page: The icon, media and README presenting a zip-installed plugin,
            base64 encoded and keyed by manifest path. Empty for repository
            installs, whose page is read from the repository at the pinned
            commit.
        digests: SHA-256 of the canonical manifest and of every file with it.
        source: Where it was installed from, for reinstalling and for display.
        granted: Permissions the user has actually granted, a subset of those
            the manifest asks for.
        config: The plugin's own stored data, opaque to PrintGuard.
        secrets: Credentials the user gave it, and the tokens an OAuth sign-in
            returned. Named in the manifest, referenced by the plugin, and never
            in anything the plugin or the dashboard reads back.
        verified: Whether these exact bytes matched a catalogue entry.
        enabled: Whether the plugin runs.
        installed: Unix timestamp of the install.
    """

    id: str
    manifest: dict[str, Any]
    sources: dict[str, str]
    digests: dict[str, str]
    source: dict[str, Any]
    assets: dict[str, str] = field(default_factory=dict)
    page: dict[str, str] = field(default_factory=dict)
    granted: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    verified: bool = False
    enabled: bool = True
    installed: float = 0.0
    failure: str | None = None

    def public(self) -> dict[str, Any]:
        """Serialises the plugin without its code for the state event.

        The state snapshot broadcasts every second, so the source travels on
        request instead, through ``plugin.code``.
        """
        return {
            "id": self.id,
            "manifest": self.manifest,
            "files": sorted(self.sources),
            "digests": self.digests,
            "source": self.source,
            "granted": self.granted,
            "config": self.config,
            "secrets_set": sorted(self.secrets),
            "verified": self.verified,
            "enabled": self.enabled,
            "installed": self.installed,
            "failure": self.failure,
        }

    def persisted(self) -> dict[str, Any]:
        """Serialises the plugin, code included, to restore it on boot."""
        return {
            "id": self.id,
            "manifest": self.manifest,
            "sources": self.sources,
            "assets": self.assets,
            "page": self.page,
            "digests": self.digests,
            "source": self.source,
            "granted": self.granted,
            "config": self.config,
            "secrets": self.secrets,
            "verified": self.verified,
            "enabled": self.enabled,
            "installed": self.installed,
        }

    def may(self, permission: str) -> bool:
        """Whether the plugin was granted a permission it asked for."""
        return permission in self.granted and permission in self.manifest["permissions"]


class CameraRegistry(Registry[Camera]):
    """Holds all registered cameras keyed by id."""

    def remove(self, camera_id: str) -> Camera | None:
        """Deregisters a camera, closing its frame source."""
        camera = super().remove(camera_id)
        if camera and camera.frame_source:
            camera.frame_source.close()
            camera.frame_source = None
        return camera

    def schedulable(self) -> list[Camera]:
        """Cameras eligible for inference, meaning in use, online and attached."""
        return [c for c in self.values() if c.in_use and c.online]

    def sync_in_use(self, monitors: dict[str, dict[str, Any]], printers: "PrinterRegistry") -> None:
        """Recomputes in_use flags from the monitors currently watching."""
        bound = {m["camera_id"] for m in monitors.values() if monitor_watching(m, printers)}
        for camera in self.values():
            camera.in_use = camera.id in bound
            if camera.frame_source:
                camera.frame_source.set_monitoring(camera.in_use)


class PrinterRegistry(Registry[Printer]):
    """Holds all registered integrated printers keyed by id."""


class TokenRegistry(Registry[Token]):
    """Holds all issued API tokens keyed by id."""


class PluginRegistry(Registry[Plugin]):
    """Holds all installed plugins keyed by their manifest id."""

    def running(self) -> list[Plugin]:
        """Enabled plugins, in install order."""
        return [p for p in self.values() if p.enabled]
