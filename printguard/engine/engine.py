"""The shared application engine.

Owns the camera and printer registries, the monitors, the scheduler and the
watchdog, and exposes a JSON command/event protocol. The UI speaks this protocol
over a WebSocket in hub mode and over an in-page bridge in local mode; the engine
cannot tell the difference.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from collections import deque
from typing import Any, Callable

from . import updates, vision
from .cameras import sanitise_camera, webrtc_endpoint
from .history import MonitorHistory
from .integrations import INTEGRATIONS, DeviceAction, integrations_meta
from .monitors import monitor_watching, persisted_monitor, sanitise_monitor
from .notifiers import NOTIFIERS, notifiers_meta
from .platform import Frame, Platform
from .printers import sanitise_printer
from .registry import Camera, CameraRegistry, Printer, PrinterRegistry, Token, TokenRegistry
from .scheduler import Scheduler
from .tokens import new_token
from .watchdog import Watchdog

STATE_TICK_S = 1.0
REATTACH_EVERY_TICKS = 10
REQUEST_TIMEOUT_S = 15.0
RECENT_EVENTS_MAX = 100
RECENT_EVENT_TYPES = ("alert", "warning", "device", "error")
UPDATE_CHECK_INTERVAL_S = 86400.0
WEBRTC_UNSUPPORTED = "WebRTC streams (WHEP/WHIP) can't be read — use the MJPEG (…?action=stream) or RTSP URL instead."

SETTINGS_DEFAULTS: dict[str, Any] = {"notifiers": {}, "update_check": True, "mqtt": {}, "theme": "system", "themes": [], "layout": {}}


class Engine:
    """Wires the shared components together and serves the protocol."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.cameras = CameraRegistry()
        self.printers = PrinterRegistry()
        self.monitors: dict[str, dict[str, Any]] = {}
        self.history: dict[str, MonitorHistory] = {}
        self.tokens = TokenRegistry()
        self.settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
        self.update: dict[str, Any] | None = None
        self.scheduler = Scheduler(platform, self.cameras, self._on_result, self._on_pipeline_error)
        self.watchdog = Watchdog(self)
        self._sinks: list[Callable[[dict[str, Any]], None]] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_EVENTS_MAX)
        self._tasks: list[asyncio.Task] = []
        self._handlers: dict[str, Any] = {
            "discover": self._cmd_discover,
            "camera.add": self._cmd_camera_add,
            "camera.update": self._cmd_camera_update,
            "camera.remove": self._cmd_camera_remove,
            "printer.add": self._cmd_printer_add,
            "printer.update": self._cmd_printer_update,
            "printer.remove": self._cmd_printer_remove,
            "printer.action": self._cmd_printer_action,
            "printer.test": self._cmd_printer_test,
            "printer.cameras.refresh": self._cmd_refresh_printer_cameras,
            "monitor.add": self._cmd_monitor_add,
            "monitor.update": self._cmd_monitor_update,
            "monitor.remove": self._cmd_monitor_remove,
            "history.get": self._cmd_history_get,
            "snapshot.get": self._cmd_snapshot_get,
            "notify.test": self._cmd_notify_test,
            "settings.update": self._cmd_settings_update,
            "token.create": self._cmd_token_create,
            "token.remove": self._cmd_token_remove,
            "update.check": self._cmd_update_check,
        }

    async def start(self) -> None:
        """Restores persisted state and launches the background loops."""
        persisted = self.platform.load_state() or {}
        self.settings = {**SETTINGS_DEFAULTS, **{k: v for k, v in persisted.get("settings", {}).items() if k in SETTINGS_DEFAULTS}}
        for record in persisted.get("tokens", []):
            self.tokens.add(Token(**record))
        for record in persisted.get("printers", []):
            try:
                printer = sanitise_printer(record["id"], record)
            except (KeyError, ValueError):
                continue
            self.printers.add(Printer(id=printer["id"], name=printer["name"], provider=printer["provider"], config=printer["config"]))
        for record in persisted.get("monitors", []):
            self.monitors[record["id"]] = sanitise_monitor(record["id"], record)
        for record in persisted.get("cameras", []):
            settings = sanitise_camera(record["id"], record)
            camera = Camera(
                id=record["id"],
                name=record["name"],
                source=record["source"],
                printer_id=record.get("printer_id"),
                max_fps=record["max_fps"],
                brightness=settings["brightness"],
                contrast=settings["contrast"],
                sharpness=settings["sharpness"],
                crop=settings["crop"],
                rotation=settings["rotation"],
            )
            self.cameras.add(camera)
            asyncio.ensure_future(self._attach(camera))
        self.cameras.sync_in_use(self.monitors, self.printers)
        self._tasks = [
            asyncio.ensure_future(self.scheduler.run()),
            asyncio.ensure_future(self.watchdog.poll_devices()),
            asyncio.ensure_future(self.watchdog.watch_health()),
            asyncio.ensure_future(self._ticker()),
        ]
        if self.platform.update_repo:
            self._tasks.append(asyncio.ensure_future(self._update_loop()))

    async def stop(self) -> None:
        """Cancels background loops and closes every frame source."""
        for task in self._tasks:
            task.cancel()
        for camera_id in list(self.cameras.items):
            self.cameras.remove(camera_id)

    def add_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        """Subscribes a transport to engine events and sends it a snapshot."""
        self._sinks.append(sink)
        sink(self.state_event())

    def remove_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        """Unsubscribes a transport."""
        if sink in self._sinks:
            self._sinks.remove(sink)

    def emit(self, event: dict[str, Any]) -> None:
        """Broadcasts an event to every connected transport."""
        if event.get("event") in RECENT_EVENT_TYPES:
            self._recent.append(event)
        for sink in list(self._sinks):
            try:
                sink(event)
            except Exception:
                self._sinks.remove(sink)

    def state_event(self) -> dict[str, Any]:
        """Builds the full state snapshot event."""
        return {
            "event": "state",
            "mode": self.platform.mode,
            "version": self.platform.version,
            "update": self.update,
            "cameras": [c.public() for c in self.cameras.values()],
            "printers": [p.public() for p in self.printers.values()],
            "monitors": [{**m, "watching": monitor_watching(m, self.printers)} for m in self.monitors.values()],
            "settings": self.settings,
            "tokens": [t.public() for t in self.tokens.values()],
            "stats": self.scheduler.stats(),
            "integrations": integrations_meta(),
            "notifiers": notifiers_meta(),
        }

    def recent_events(self) -> list[dict[str, Any]]:
        """Returns the retained tail of alert, warning, device and error events."""
        return list(self._recent)

    def token_scopes(self) -> dict[str, str]:
        """Maps each issued token's secret hash to the scope it grants."""
        return {t.hash: t.scope for t in self.tokens.values()}

    async def handle(self, message: dict[str, Any]) -> None:
        """Executes a protocol command, emitting an error event on failure."""
        handler = self._handlers.get(message.get("cmd", ""))
        if not handler:
            self.emit({"event": "error", "message": f"unknown command {message.get('cmd')!r}"})
            return
        req_id = message.get("req_id")
        try:
            await handler(message)
            self._sync(req_id)
        except Exception as exc:
            self.emit({"event": "error", "message": str(exc), "req_id": req_id})

    async def request(self, message: dict[str, Any], *, timeout: float = REQUEST_TIMEOUT_S) -> list[dict[str, Any]]:
        """Runs a command and returns the events it produced, raising on failure.

        A correlating req_id is attached, a temporary sink collects every event
        carrying it, and handle() emits the command's events (the terminal state
        snapshot, or an error) before it returns. This turns the broadcast
        protocol into the request/response shape the REST and MCP transports need
        without duplicating any command logic.
        """
        req_id = uuid.uuid4().hex
        collected: list[dict[str, Any]] = []

        def sink(event: dict[str, Any]) -> None:
            if event.get("req_id") == req_id:
                collected.append(event)

        self.add_sink(sink)
        try:
            await asyncio.wait_for(self.handle({**message, "req_id": req_id}), timeout)
        finally:
            self.remove_sink(sink)
        for event in collected:
            if event.get("event") == "error":
                raise RuntimeError(event.get("message", "command failed"))
        return collected

    async def snapshot(self, camera_id: str) -> bytes | None:
        """Encodes the freshest frame of a camera as JPEG, or None if unavailable.

        Applies the camera's image pipeline (rotation, crop, adjustments) so the
        snapshot matches the live view and the frame the model infers on.
        """
        camera = self.cameras.get(camera_id)
        if camera is None or camera.frame_source is None:
            return None
        frame = await camera.frame_source.grab()
        if frame is None:
            return None
        rgb = vision.transform(
            frame.rgb,
            rotation=camera.rotation,
            crop=camera.crop,
            brightness=camera.brightness,
            contrast=camera.contrast,
            sharpness=camera.sharpness,
        )
        return await self.platform.encode_jpeg(rgb)

    def _save(self) -> None:
        self.platform.save_state(
            {
                "cameras": [c.persisted() for c in self.cameras.values()],
                "printers": [p.persisted() for p in self.printers.values()],
                "monitors": [persisted_monitor(m) for m in self.monitors.values()],
                "settings": self.settings,
                "tokens": [t.persisted() for t in self.tokens.values()],
            }
        )

    def _sync(self, req_id: Any = None) -> None:
        self.cameras.sync_in_use(self.monitors, self.printers)
        self._save()
        event = self.state_event()
        if req_id is not None:
            event["req_id"] = req_id
        self.emit(event)

    async def _attach(self, camera: Camera) -> None:
        try:
            source = await self.platform.open_camera(camera.id, camera.source)
        except Exception:
            return
        camera.frame_source = source
        if source.fps > 0:
            camera.max_fps = source.fps

    async def _ticker(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(STATE_TICK_S)
            tick += 1
            for camera in self.cameras.values():
                if camera.frame_source is None:
                    if tick % REATTACH_EVERY_TICKS == 0:
                        asyncio.ensure_future(self._attach(camera))
                elif camera.frame_source.fps > 0:
                    camera.max_fps = camera.frame_source.fps
            self.emit(self.state_event())

    async def _update_loop(self) -> None:
        """Refreshes the update status daily while the auto-check is enabled."""
        while True:
            if self.settings.get("update_check", True):
                try:
                    await self._check_updates()
                    self.emit(self.state_event())
                except Exception:
                    pass
            await asyncio.sleep(UPDATE_CHECK_INTERVAL_S)

    async def _check_updates(self) -> None:
        """Fetches and stores the update status, raising if it cannot."""
        if not self.platform.update_repo:
            raise RuntimeError("update checks are not available in this mode")
        self.update = await updates.fetch_updates(self.platform.http, self.platform.update_repo, self.platform.version)

    def _on_pipeline_error(self, message: str) -> None:
        self.emit({"event": "error", "message": message})

    async def _on_result(self, camera: Camera, frame: Frame, result: dict[str, Any]) -> None:
        for monitor in self.monitors.values():
            if monitor["camera_id"] != camera.id or not monitor_watching(monitor, self.printers):
                continue
            score = vision.defect_score(result, monitor["sensitivity"])
            ts = time.time()
            self.emit(
                {
                    "event": "result",
                    "monitor_id": monitor["id"],
                    "camera_id": camera.id,
                    "score": round(score, 4),
                    "prediction": "failure" if score >= monitor["threshold"] else "success",
                    "margin": round(result.get("margin", 0.0), 4),
                    "ms": self.scheduler.stats()["infer_ms"],
                    "ts": ts,
                }
            )
            self.history.setdefault(monitor["id"], MonitorHistory()).record(ts, score, monitor["threshold"])
            await self.watchdog.on_score(monitor, frame, score)

    def note_alert(self, monitor_id: str, alert: dict[str, Any], jpeg: bytes | None) -> None:
        """Records a fired alert and its triggering frame in a monitor's history."""
        self.history.setdefault(monitor_id, MonitorHistory()).record_alert(alert["ts"], alert["score"], alert["action"], jpeg)

    def monitor_snapshot(self, monitor_id: str, snap_id: str) -> bytes | None:
        """Returns a captured risky-moment snapshot's JPEG bytes, or None."""
        history = self.history.get(monitor_id)
        return history.snapshot(snap_id) if history else None

    async def _cmd_discover(self, message: dict[str, Any]) -> None:
        sources = await self.platform.discover_cameras()
        registered = {c.source.get("device_id") or c.source.get("path") or c.source.get("url") for c in self.cameras.values()}
        fresh = [s for s in sources if (s.get("device_id") or s.get("path") or s.get("url")) not in registered]
        self.emit({"event": "discovered", "sources": fresh, "req_id": message.get("req_id")})

    async def _cmd_camera_add(self, message: dict[str, Any]) -> None:
        source = dict(message["source"])
        if source.get("kind") == "url" and webrtc_endpoint(str(source.get("url") or "")):
            raise ValueError(WEBRTC_UNSUPPORTED)
        camera_id = uuid.uuid4().hex[:8]
        camera = Camera(
            id=camera_id,
            name=str(message.get("name") or "Camera").strip() or "Camera",
            source=source,
            max_fps=15.0,
        )
        source = await self.platform.open_camera(camera_id, camera.source)
        camera.frame_source = source
        if source.fps > 0:
            camera.max_fps = source.fps
        self.cameras.add(camera)

    async def _cmd_camera_update(self, message: dict[str, Any]) -> None:
        camera = self.cameras.get(message["id"])
        if not camera:
            raise KeyError(f"no camera {message['id']}")
        settings = sanitise_camera(
            camera.id,
            message.get("patch", {}),
            {
                "brightness": camera.brightness,
                "contrast": camera.contrast,
                "sharpness": camera.sharpness,
                "crop": camera.crop,
                "rotation": camera.rotation,
            },
        )
        if "name" in message.get("patch", {}):
            camera.name = settings["name"]
        camera.brightness = settings["brightness"]
        camera.contrast = settings["contrast"]
        camera.sharpness = settings["sharpness"]
        camera.crop = settings["crop"]
        camera.rotation = settings["rotation"]

    async def _cmd_camera_remove(self, message: dict[str, Any]) -> None:
        camera = self.cameras.get(message["id"])
        if camera and camera.printer_id and self.printers.get(camera.printer_id):
            raise RuntimeError("camera is managed by its printer integration; remove the printer instead")
        await self._drop_camera(message["id"])

    async def _drop_camera(self, camera_id: str) -> None:
        camera = self.cameras.remove(camera_id)
        if camera:
            await self.platform.release_camera(camera.id, camera.source)
        for monitor in self.monitors.values():
            if monitor["camera_id"] == camera_id:
                monitor["camera_id"] = ""

    async def _cmd_refresh_printer_cameras(self, message: dict[str, Any]) -> None:
        """Re-checks every printer and registers any newly exposed cameras.

        This is the manual counterpart to the automatic reconcile on printer
        add/update: the user triggers it from the camera registry to pick up a
        camera attached to a printer's service after it was registered.
        """
        await asyncio.gather(*(self.reconcile_printer_cameras(printer) for printer in self.printers.values()))

    async def reconcile_printer_cameras(self, printer: Printer) -> None:
        """Registers any cameras a printer's service exposes that are not known yet.

        Runs when a printer is added or updated, and on demand via
        printer.cameras.refresh. A deterministic id keyed by the adapter's camera
        key makes this idempotent; cameras the service stops exposing are left in
        place and go only when the printer does.
        """
        adapter = INTEGRATIONS.get(printer.provider)
        if not adapter:
            return
        try:
            exposed = await adapter.cameras(self.platform.http, printer.config)
        except Exception:
            return
        if self.printers.get(printer.id) is None:
            return
        added = False
        for descriptor in exposed:
            camera_id = f"{printer.id}-{descriptor['key']}"
            if self.cameras.get(camera_id):
                continue
            source = dict(descriptor["source"])
            if source.get("kind") == "url" and webrtc_endpoint(str(source.get("url") or "")):
                self.emit({"event": "warning", "printer_id": printer.id, "message": f"{descriptor['name']}: {WEBRTC_UNSUPPORTED}"})
                continue
            camera = Camera(id=camera_id, name=descriptor["name"], source=source, printer_id=printer.id, max_fps=15.0)
            try:
                source = await self.platform.open_camera(camera_id, camera.source)
            except Exception:
                continue
            camera.frame_source = source
            if source.fps > 0:
                camera.max_fps = source.fps
            self.cameras.add(camera)
            added = True
        if added:
            self._sync()

    async def _cmd_printer_add(self, message: dict[str, Any]) -> None:
        printer_id = uuid.uuid4().hex[:8]
        record = sanitise_printer(printer_id, message.get("printer", {}))
        printer = Printer(id=printer_id, name=record["name"], provider=record["provider"], config=record["config"])
        self.printers.add(printer)
        asyncio.ensure_future(self.reconcile_printer_cameras(printer))

    async def _cmd_printer_update(self, message: dict[str, Any]) -> None:
        existing = self.printers.get(message["id"])
        if not existing:
            raise KeyError(f"no printer {message['id']}")
        record = sanitise_printer(existing.id, message.get("patch", {}), existing.persisted())
        if record["provider"] != existing.provider:
            existing.device_state = None
            for camera in [c for c in self.cameras.values() if c.printer_id == existing.id]:
                await self._drop_camera(camera.id)
        existing.name = record["name"]
        existing.provider = record["provider"]
        existing.config = record["config"]
        asyncio.ensure_future(self.reconcile_printer_cameras(existing))

    async def _cmd_printer_remove(self, message: dict[str, Any]) -> None:
        self.printers.remove(message["id"])
        for camera in [c for c in self.cameras.values() if c.printer_id == message["id"]]:
            await self._drop_camera(camera.id)
        for monitor in self.monitors.values():
            if monitor.get("printer_id") == message["id"]:
                monitor["printer_id"] = ""

    async def _cmd_printer_action(self, message: dict[str, Any]) -> None:
        printer = self.printers.get(message["id"])
        if not printer:
            raise KeyError(f"no printer {message['id']}")
        adapter = INTEGRATIONS.get(printer.provider)
        if not adapter:
            raise RuntimeError("no printer service linked")
        await adapter.send(self.platform.http, printer.config, DeviceAction(message["action"]))
        state = await adapter.fetch_state(self.platform.http, printer.config)
        printer.device_state = state.public()
        self.emit({"event": "device", "printer_id": printer.id, **printer.device_state})

    async def _cmd_printer_test(self, message: dict[str, Any]) -> None:
        adapter = INTEGRATIONS.get(message.get("provider") or "")
        if not adapter:
            raise RuntimeError(f"unknown provider {message.get('provider')!r}")
        try:
            state = await adapter.fetch_state(self.platform.http, message.get("config", {}))
            ok = state.status.value not in ("offline", "unknown")
            self.emit({"event": "printer_test", "ok": ok, "status": state.status.value, "req_id": message.get("req_id")})
        except Exception as exc:
            self.emit({"event": "printer_test", "ok": False, "status": None, "error": str(exc), "req_id": message.get("req_id")})

    async def _cmd_monitor_add(self, message: dict[str, Any]) -> None:
        monitor_id = uuid.uuid4().hex[:8]
        self.monitors[monitor_id] = sanitise_monitor(monitor_id, message.get("monitor", {}))

    async def _cmd_monitor_update(self, message: dict[str, Any]) -> None:
        existing = self.monitors.get(message["id"])
        if not existing:
            raise KeyError(f"no monitor {message['id']}")
        self.monitors[message["id"]] = sanitise_monitor(message["id"], message.get("patch", {}), existing)

    async def _cmd_monitor_remove(self, message: dict[str, Any]) -> None:
        self.monitors.pop(message["id"], None)
        self.history.pop(message["id"], None)

    async def _cmd_history_get(self, message: dict[str, Any]) -> None:
        history = self.history.get(message["monitor_id"])
        series = history.series() if history else {"buckets": [], "snaps": [], "alerts": [], "stats": {}}
        self.emit({"event": "history", "monitor_id": message["monitor_id"], **series, "req_id": message.get("req_id")})

    async def _cmd_snapshot_get(self, message: dict[str, Any]) -> None:
        jpeg = self.monitor_snapshot(message["monitor_id"], message["id"])
        if jpeg is None:
            raise KeyError(f"no snapshot {message['id']!r}")
        self.emit({"event": "snapshot", "id": message["id"], "jpeg": base64.b64encode(jpeg).decode(), "req_id": message.get("req_id")})

    async def _cmd_notify_test(self, message: dict[str, Any]) -> None:
        adapter = NOTIFIERS.get(message.get("provider") or "")
        if not adapter:
            raise RuntimeError(f"unknown notifier {message.get('provider')!r}")
        try:
            await adapter.send(self.platform.http, message.get("config", {}), "PrintGuard test", "Notifications are working.", None)
            self.emit({"event": "notify_test", "provider": adapter.id, "ok": True, "req_id": message.get("req_id")})
        except Exception as exc:
            self.emit({"event": "notify_test", "provider": adapter.id, "ok": False, "error": str(exc), "req_id": message.get("req_id")})

    async def _cmd_settings_update(self, message: dict[str, Any]) -> None:
        self.settings = {**self.settings, **{k: v for k, v in message.get("patch", {}).items() if k in SETTINGS_DEFAULTS}}

    async def _cmd_token_create(self, message: dict[str, Any]) -> None:
        name = str(message.get("name") or "token").strip() or "token"
        record, secret = new_token(name, message.get("scope") or "read")
        token = Token(**record)
        self.tokens.add(token)
        self.emit({"event": "token_created", **token.public(), "token": secret, "req_id": message.get("req_id")})

    async def _cmd_token_remove(self, message: dict[str, Any]) -> None:
        self.tokens.remove(message["id"])

    async def _cmd_update_check(self, message: dict[str, Any]) -> None:
        await self._check_updates()
