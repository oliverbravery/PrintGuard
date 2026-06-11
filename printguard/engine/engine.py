"""The shared application engine.

Owns the camera registry, printers, scheduler and monitor, and exposes a
JSON command/event protocol. The UI speaks this protocol over a WebSocket
in hub mode and over an in-page bridge in local mode; the engine cannot
tell the difference.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from . import vision
from .integrations import INTEGRATIONS, DeviceAction, integrations_meta
from .monitor import Monitor
from .platform import Frame, Platform
from .printers import persisted_printer, sanitise_printer
from .registry import Camera, CameraRegistry
from .scheduler import Scheduler

STATE_TICK_S = 1.0
REATTACH_EVERY_TICKS = 10

SETTINGS_DEFAULTS: dict[str, Any] = {"ntfy_url": "", "whep_base": ""}


class Engine:
    """Wires the shared components together and serves the protocol."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.registry = CameraRegistry()
        self.printers: dict[str, dict[str, Any]] = {}
        self.settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
        self.scheduler = Scheduler(platform, self.registry, self._on_result)
        self.monitor = Monitor(self)
        self._sinks: list[Callable[[dict[str, Any]], None]] = []
        self._tasks: list[asyncio.Task] = []
        self._handlers: dict[str, Any] = {
            "discover": self._cmd_discover,
            "camera.add": self._cmd_camera_add,
            "camera.remove": self._cmd_camera_remove,
            "printer.add": self._cmd_printer_add,
            "printer.update": self._cmd_printer_update,
            "printer.remove": self._cmd_printer_remove,
            "printer.action": self._cmd_printer_action,
            "device.test": self._cmd_device_test,
            "settings.update": self._cmd_settings_update,
        }

    async def start(self) -> None:
        """Restores persisted state and launches the background loops."""
        persisted = self.platform.load_state() or {}
        self.settings = {**SETTINGS_DEFAULTS, **persisted.get("settings", {})}
        for record in persisted.get("printers", []):
            self.printers[record["id"]] = sanitise_printer(record["id"], record)
        for record in persisted.get("cameras", []):
            camera = Camera(id=record["id"], name=record["name"], source=record["source"], max_fps=record["max_fps"])
            self.registry.add(camera)
            asyncio.ensure_future(self._attach(camera))
        self.registry.sync_in_use(self.printers)
        self._tasks = [
            asyncio.ensure_future(self.scheduler.run()),
            asyncio.ensure_future(self.monitor.poll_devices()),
            asyncio.ensure_future(self._ticker()),
        ]

    async def stop(self) -> None:
        """Cancels background loops and closes every frame source."""
        for task in self._tasks:
            task.cancel()
        for camera_id in list(self.registry.cameras):
            self.registry.remove(camera_id)

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
            "cameras": [c.public() for c in self.registry.cameras.values()],
            "printers": list(self.printers.values()),
            "settings": self.settings,
            "stats": self.scheduler.stats(),
            "integrations": integrations_meta(),
        }

    async def handle(self, message: dict[str, Any]) -> None:
        """Executes a protocol command, emitting an error event on failure."""
        handler = self._handlers.get(message.get("cmd", ""))
        if not handler:
            self.emit({"event": "error", "message": f"unknown command {message.get('cmd')!r}"})
            return
        try:
            await handler(message)
        except Exception as exc:
            self.emit({"event": "error", "message": str(exc), "req_id": message.get("req_id")})

    def _save(self) -> None:
        self.platform.save_state(
            {
                "cameras": [c.persisted() for c in self.registry.cameras.values()],
                "printers": [persisted_printer(p) for p in self.printers.values()],
                "settings": self.settings,
            }
        )

    def _sync(self) -> None:
        self.registry.sync_in_use(self.printers)
        self._save()
        self.emit(self.state_event())

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
            if tick % REATTACH_EVERY_TICKS == 0:
                for camera in self.registry.cameras.values():
                    if camera.frame_source is None:
                        asyncio.ensure_future(self._attach(camera))
            self.emit(self.state_event())

    async def _on_result(self, camera: Camera, frame: Frame, result: dict[str, Any]) -> None:
        for printer in self.printers.values():
            if printer["camera_id"] != camera.id or not printer["enabled"]:
                continue
            score = vision.defect_score(result, printer["sensitivity"])
            self.emit(
                {
                    "event": "result",
                    "printer_id": printer["id"],
                    "camera_id": camera.id,
                    "score": round(score, 4),
                    "prediction": "failure" if score >= printer["threshold"] else "success",
                    "margin": round(result.get("margin", 0.0), 4),
                    "ms": self.scheduler.stats()["infer_ms"],
                    "ts": time.time(),
                }
            )
            await self.monitor.on_score(printer, frame, score)

    async def _cmd_discover(self, message: dict[str, Any]) -> None:
        sources = await self.platform.discover_cameras()
        registered = {c.source.get("device_id") or c.source.get("path") or c.source.get("url") for c in self.registry.cameras.values()}
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
        self.registry.add(camera)
        self._sync()

    async def _cmd_camera_remove(self, message: dict[str, Any]) -> None:
        camera = self.registry.remove(message["id"])
        if camera:
            await self.platform.release_camera(camera.id, camera.source)
        for printer in self.printers.values():
            if printer["camera_id"] == message["id"]:
                printer["camera_id"] = ""
        self._sync()

    async def _cmd_printer_add(self, message: dict[str, Any]) -> None:
        printer_id = uuid.uuid4().hex[:8]
        self.printers[printer_id] = sanitise_printer(printer_id, message.get("printer", {}))
        self._sync()

    async def _cmd_printer_update(self, message: dict[str, Any]) -> None:
        existing = self.printers.get(message["id"])
        if not existing:
            raise KeyError(f"no printer {message['id']}")
        self.printers[message["id"]] = sanitise_printer(message["id"], message.get("patch", {}), existing)
        self._sync()

    async def _cmd_printer_remove(self, message: dict[str, Any]) -> None:
        self.printers.pop(message["id"], None)
        self._sync()

    async def _cmd_printer_action(self, message: dict[str, Any]) -> None:
        printer = self.printers[message["id"]]
        adapter = INTEGRATIONS.get(printer["device"].get("provider") or "")
        if not adapter:
            raise RuntimeError("no printer service linked")
        await adapter.send(self.platform.http, printer["device"]["config"], DeviceAction(message["action"]))
        state = await adapter.fetch_state(self.platform.http, printer["device"]["config"])
        printer["device_state"] = state.public()
        self.emit({"event": "device", "printer_id": printer["id"], **printer["device_state"]})

    async def _cmd_device_test(self, message: dict[str, Any]) -> None:
        adapter = INTEGRATIONS.get(message.get("provider") or "")
        if not adapter:
            raise RuntimeError(f"unknown provider {message.get('provider')!r}")
        try:
            state = await adapter.fetch_state(self.platform.http, message.get("config", {}))
            ok = state.status.value not in ("offline", "unknown")
            self.emit({"event": "device_test", "ok": ok, "status": state.status.value, "req_id": message.get("req_id")})
        except Exception as exc:
            self.emit({"event": "device_test", "ok": False, "status": None, "error": str(exc), "req_id": message.get("req_id")})

    async def _cmd_settings_update(self, message: dict[str, Any]) -> None:
        self.settings = {**self.settings, **{k: v for k, v in message.get("patch", {}).items() if k in SETTINGS_DEFAULTS}}
        self._sync()
