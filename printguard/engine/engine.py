"""The shared application engine.

Owns the camera and printer registries, the monitors, the scheduler and the
watchdog, and exposes a JSON command/event protocol. The UI speaks this protocol
over a WebSocket in hub mode and over an in-page bridge in local mode; the engine
cannot tell the difference.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Any, Callable

from . import vision
from .cameras import sanitise_camera
from .integrations import INTEGRATIONS, DeviceAction, integrations_meta
from .monitors import monitor_watching, persisted_monitor, sanitise_monitor
from .notifiers import NOTIFIERS, notifiers_meta
from .platform import Frame, Platform
from .printers import sanitise_printer
from .registry import Camera, CameraRegistry, Printer, PrinterRegistry
from .scheduler import Scheduler
from .watchdog import Watchdog

STATE_TICK_S = 1.0
REATTACH_EVERY_TICKS = 10
REQUEST_TIMEOUT_S = 15.0
RECENT_EVENTS_MAX = 100
RECENT_EVENT_TYPES = ("alert", "warning", "device", "error")

SETTINGS_DEFAULTS: dict[str, Any] = {"notifiers": {}}


class Engine:
    """Wires the shared components together and serves the protocol."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.cameras = CameraRegistry()
        self.printers = PrinterRegistry()
        self.monitors: dict[str, dict[str, Any]] = {}
        self.settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
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
            "monitor.add": self._cmd_monitor_add,
            "monitor.update": self._cmd_monitor_update,
            "monitor.remove": self._cmd_monitor_remove,
            "notify.test": self._cmd_notify_test,
            "settings.update": self._cmd_settings_update,
        }

    async def start(self) -> None:
        """Restores persisted state and launches the background loops."""
        persisted = self.platform.load_state() or {}
        self.settings = {**SETTINGS_DEFAULTS, **{k: v for k, v in persisted.get("settings", {}).items() if k in SETTINGS_DEFAULTS}}
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
                max_fps=record["max_fps"],
                brightness=settings["brightness"],
                contrast=settings["contrast"],
                sharpness=settings["sharpness"],
                crop=settings["crop"],
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
            "cameras": [c.public() for c in self.cameras.values()],
            "printers": [p.public() for p in self.printers.values()],
            "monitors": [{**m, "watching": monitor_watching(m, self.printers)} for m in self.monitors.values()],
            "settings": self.settings,
            "stats": self.scheduler.stats(),
            "integrations": integrations_meta(),
            "notifiers": notifiers_meta(),
        }

    def recent_events(self) -> list[dict[str, Any]]:
        """Returns the retained tail of alert, warning, device and error events."""
        return list(self._recent)

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
        """Encodes the freshest frame of a camera as JPEG, or None if unavailable."""
        camera = self.cameras.get(camera_id)
        if camera is None or camera.frame_source is None:
            return None
        frame = await camera.frame_source.grab()
        if frame is None:
            return None
        return await self.platform.encode_jpeg(frame.rgb)

    def _save(self) -> None:
        self.platform.save_state(
            {
                "cameras": [c.persisted() for c in self.cameras.values()],
                "printers": [p.persisted() for p in self.printers.values()],
                "monitors": [persisted_monitor(m) for m in self.monitors.values()],
                "settings": self.settings,
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

    def _on_pipeline_error(self, message: str) -> None:
        self.emit({"event": "error", "message": message})

    async def _on_result(self, camera: Camera, frame: Frame, result: dict[str, Any]) -> None:
        for monitor in self.monitors.values():
            if monitor["camera_id"] != camera.id or not monitor_watching(monitor, self.printers):
                continue
            score = vision.defect_score(result, monitor["sensitivity"])
            self.emit(
                {
                    "event": "result",
                    "monitor_id": monitor["id"],
                    "camera_id": camera.id,
                    "score": round(score, 4),
                    "prediction": "failure" if score >= monitor["threshold"] else "success",
                    "margin": round(result.get("margin", 0.0), 4),
                    "ms": self.scheduler.stats()["infer_ms"],
                    "ts": time.time(),
                }
            )
            await self.watchdog.on_score(monitor, frame, score)

    async def _cmd_discover(self, message: dict[str, Any]) -> None:
        sources = await self.platform.discover_cameras()
        registered = {c.source.get("device_id") or c.source.get("path") or c.source.get("url") for c in self.cameras.values()}
        fresh = [s for s in sources if (s.get("device_id") or s.get("path") or s.get("url")) not in registered]
        self.emit({"event": "discovered", "sources": fresh, "req_id": message.get("req_id")})

    async def _cmd_camera_add(self, message: dict[str, Any]) -> None:
        camera_id = uuid.uuid4().hex[:8]
        camera = Camera(
            id=camera_id,
            name=str(message.get("name") or "Camera").strip() or "Camera",
            source=dict(message["source"]),
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
            {"brightness": camera.brightness, "contrast": camera.contrast, "sharpness": camera.sharpness, "crop": camera.crop},
        )
        if "name" in message.get("patch", {}):
            camera.name = settings["name"]
        camera.brightness = settings["brightness"]
        camera.contrast = settings["contrast"]
        camera.sharpness = settings["sharpness"]
        camera.crop = settings["crop"]

    async def _cmd_camera_remove(self, message: dict[str, Any]) -> None:
        camera = self.cameras.remove(message["id"])
        if camera:
            await self.platform.release_camera(camera.id, camera.source)
        for monitor in self.monitors.values():
            if monitor["camera_id"] == message["id"]:
                monitor["camera_id"] = ""

    async def _cmd_printer_add(self, message: dict[str, Any]) -> None:
        printer_id = uuid.uuid4().hex[:8]
        record = sanitise_printer(printer_id, message.get("printer", {}))
        self.printers.add(Printer(id=printer_id, name=record["name"], provider=record["provider"], config=record["config"]))

    async def _cmd_printer_update(self, message: dict[str, Any]) -> None:
        existing = self.printers.get(message["id"])
        if not existing:
            raise KeyError(f"no printer {message['id']}")
        record = sanitise_printer(existing.id, message.get("patch", {}), existing.persisted())
        if record["provider"] != existing.provider:
            existing.device_state = None
        existing.name = record["name"]
        existing.provider = record["provider"]
        existing.config = record["config"]

    async def _cmd_printer_remove(self, message: dict[str, Any]) -> None:
        self.printers.remove(message["id"])
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
