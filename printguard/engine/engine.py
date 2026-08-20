"""The shared application engine.

Owns the camera and printer registries, the monitors, the scheduler and the
watchdog, and exposes a JSON command/event protocol. The UI speaks this protocol
over a WebSocket in hub mode and over an in-page bridge in local mode; the engine
cannot tell the difference.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from typing import Any, Callable

from . import oauth, plugins, reports, updates, urls, vision
from .cameras import sanitise_camera
from .history import MonitorHistory
from .integrations import INTEGRATIONS, DeviceAction, integrations_meta
from .monitors import monitor_watching, persisted_monitor, sanitise_monitor
from .notifiers import NOTIFIERS, notifiers_meta
from .platform import Frame, Platform
from .printers import sanitise_printer
from .registry import Camera, CameraRegistry, Plugin, PluginRegistry, Printer, PrinterRegistry, Token, TokenRegistry
from .scheduler import Scheduler
from .sockets import SocketBroker
from .tokens import new_token
from .watchdog import Watchdog

logger = logging.getLogger(__name__)

STATE_TICK_S = 1.0
RESULT_EVENT_INTERVAL_S = 0.2
REATTACH_EVERY_TICKS = 10
REQUEST_TIMEOUT_S = 15.0
RECENT_EVENTS_MAX = 100
RECENT_EVENT_TYPES = ("alert", "warning", "device", "error")
EVENT_LOG_LEVELS = {"alert": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR, "device": logging.DEBUG}
UPDATE_CHECK_INTERVAL_S = 86400.0
PLUGIN_RATE_LIMIT = 60
PLUGIN_RATE_WINDOW_S = 60.0
PLUGIN_TIMEOUT_S = 10.0
MAX_PLUGIN_BODY = 256 * 1024
CALL_TTL_S = 30.0
SETTINGS_DEFAULTS: dict[str, Any] = {
    "notifiers": {},
    "update_check": True,
    "mqtt": {},
    "theme": "system",
    "themes": [],
    "layout": {},
    "inference_runtime": "auto",
    "catalogue_url": plugins.CATALOGUE_URL,
}


class Engine:
    """Wires the shared components together and serves the protocol."""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.cameras = CameraRegistry()
        self.printers = PrinterRegistry()
        self.monitors: dict[str, dict[str, Any]] = {}
        self.history: dict[str, MonitorHistory] = {}
        self._results: dict[str, dict[str, float]] = {}
        self._result_emitted_at: dict[str, float] = {}
        self.tokens = TokenRegistry()
        self.plugins = PluginRegistry()
        self.catalogue: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = dict(SETTINGS_DEFAULTS)
        self.update: dict[str, Any] | None = None
        self.releases: list[dict[str, Any]] = []
        self.scheduler = Scheduler(platform, self.cameras, self._on_result, self._on_pipeline_error)
        self.watchdog = Watchdog(self)
        self.sockets = SocketBroker(platform.open_socket, self.emit)
        self.oauth = oauth.OAuthFlows(platform.http)
        self._plugin_calls: dict[str, list[float]] = {}
        self._pending_calls: dict[str, tuple[str, str, str, float]] = {}
        self._sinks: list[Callable[[dict[str, Any]], None]] = []
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_EVENTS_MAX)
        self._tasks: list[asyncio.Task[None]] = []
        self._attach_tasks: dict[str, asyncio.Task[None]] = {}
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
            "camera.snapshot": self._cmd_camera_snapshot,
            "notify.test": self._cmd_notify_test,
            "notify.send": self._cmd_notify_send,
            "settings.update": self._cmd_settings_update,
            "token.create": self._cmd_token_create,
            "token.remove": self._cmd_token_remove,
            "update.check": self._cmd_update_check,
            "update.releases": self._cmd_update_releases,
            "report.send": self._cmd_report_send,
            "report.bundle": self._cmd_report_bundle,
            "plugin.install": self._cmd_plugin_install,
            "plugin.remove": self._cmd_plugin_remove,
            "plugin.update": self._cmd_plugin_update,
            "plugin.code": self._cmd_plugin_code,
            "plugin.catalogue": self._cmd_plugin_catalogue,
            "plugin.http": self._cmd_plugin_http,
            "plugin.socket": self._cmd_plugin_socket,
            "plugin.call": self._cmd_plugin_call,
            "plugin.answer": self._cmd_plugin_answer,
            "plugin.publish": self._cmd_plugin_publish,
            "plugin.secrets": self._cmd_plugin_secrets,
            "plugin.oauth": self._cmd_plugin_oauth,
            "plugin.notify": self._cmd_plugin_notify,
        }

    async def start(self) -> None:
        """Restores persisted state and launches the background loops."""
        persisted = self.platform.load_state() or {}
        self.settings = {**SETTINGS_DEFAULTS, **{k: v for k, v in persisted.get("settings", {}).items() if k in SETTINGS_DEFAULTS}}
        await self.platform.configure(self.settings)
        self.scheduler.reset()
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
        for record in persisted.get("plugins", []):
            try:
                self.plugins.add(Plugin(**record))
            except TypeError:
                logger.warning("dropping unreadable plugin record %r", record.get("id"))
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
            self._schedule_attach(camera)
        self.cameras.sync_in_use(self.monitors, self.printers)
        runtime = self.platform.plugin_runtime
        if runtime is not None:
            runtime.attach(self.request, self.plugin_failed)
            self.add_sink(runtime.on_event)
            await runtime.reload(self.plugins.running())
        self._tasks = [
            asyncio.ensure_future(self.scheduler.run()),
            asyncio.ensure_future(self.watchdog.poll_devices()),
            asyncio.ensure_future(self.watchdog.watch_health()),
            asyncio.ensure_future(self._ticker()),
        ]
        if self.platform.update_repo:
            self._tasks.append(asyncio.ensure_future(self._update_loop()))
        logger.info(
            "engine started: v%s %s, %d cameras, %d printers, %d monitors restored",
            self.platform.version,
            self.platform.mode,
            len(self.cameras.items),
            len(self.printers.items),
            len(self.monitors),
        )

    async def stop(self) -> None:
        """Cancels background loops and closes every frame source."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.sockets.drop_all(set())
        await self.watchdog.close()
        if self.platform.plugin_runtime is not None:
            await self.platform.plugin_runtime.close()
        for camera_id in list(self.cameras.items):
            await self._drop_camera(camera_id)
        await asyncio.gather(*(adapter.close() for adapter in INTEGRATIONS.values()))
        logger.info("engine stopped")

    def add_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        """Subscribes a transport to engine events and sends it a snapshot."""
        self._sinks.append(sink)
        sink(self.state_event())

    def remove_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        """Unsubscribes a transport."""
        if sink in self._sinks:
            self._sinks.remove(sink)

    def emit(self, event: dict[str, Any]) -> None:
        """Logs the event when loggable, then broadcasts it to every transport.

        Alert, warning, error and device events are also written to the log,
        so the log tail carries the same timeline a maintainer sees in a bug
        report's recent events - plus everything around it.
        """
        level = EVENT_LOG_LEVELS.get(event.get("event", ""))
        if level is not None:
            logger.log(level, "%s %s", event["event"], {k: v for k, v in event.items() if k not in ("event", "req_id")})
        self._broadcast(event)

    def _broadcast(self, event: dict[str, Any]) -> None:
        """Delivers an event to recent history and every transport sink.

        Kept separate from emit() so an event carrying a one-time secret
        (token_created) can reach the requesting transport without ever being
        written to the log in clear text.
        """
        if event.get("event") in RECENT_EVENT_TYPES:
            self._recent.append(event)
        for sink in list(self._sinks):
            try:
                sink(event)
            except Exception:
                logger.warning("dropping transport sink that failed to accept an event", exc_info=True)
                self._sinks.remove(sink)

    def state_event(self) -> dict[str, Any]:
        """Builds the full state snapshot event."""
        return {
            "event": "state",
            "mode": self.platform.mode,
            "host": self.platform.host,
            "version": self.platform.version,
            "update": self.update,
            "cameras": [c.public() for c in self.cameras.values()],
            "printers": [p.public() for p in self.printers.values()],
            "monitors": [
                {
                    **monitor,
                    "watching": monitor_watching(monitor, self.printers),
                    "result": self._results.get(monitor["id"]),
                }
                for monitor in self.monitors.values()
            ],
            "settings": self.settings,
            "tokens": [t.public() for t in self.tokens.values()],
            "stats": self.scheduler.stats(),
            "integrations": integrations_meta(),
            "notifiers": notifiers_meta(),
            "plugins": [p.public() for p in self.plugins.values()],
            "plugin_permissions": plugins.permissions_meta(),
            "plugin_events": plugins.EVENTS,
            "plugin_event_permissions": plugins.EVENT_PERMISSIONS,
            "plugin_platforms": plugins.PLATFORMS,
            "plugin_assets": plugins.ASSET_TYPES,
            "plugin_host": self.platform.plugin_runtime is not None,
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
        logger.debug("command %s", message.get("cmd"))
        try:
            await handler(message)
            self._sync(req_id)
        except Exception as exc:
            logger.warning("command %s failed", message.get("cmd"), exc_info=True)
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

    async def classify(self, data: bytes, sensitivity: float = 1.0) -> dict[str, Any]:
        """Classifies a supplied frame, returning the model's verdict and defect score.

        Decodes the image on the platform and runs the same inference the scheduler
        uses - the stateless equivalent of a camera's latest per-frame result, for a
        frame the caller already holds rather than one PrintGuard pulls itself.
        """
        rgb = await self.platform.decode_jpeg(data)
        if rgb is None:
            raise RuntimeError("could not decode image")
        result = await self.platform.infer(rgb)
        return {**result, "defect_score": vision.defect_score(result, sensitivity)}

    def _save(self) -> None:
        self.platform.save_state(
            {
                "cameras": [c.persisted() for c in self.cameras.values()],
                "printers": [p.persisted() for p in self.printers.values()],
                "monitors": [persisted_monitor(m) for m in self.monitors.values()],
                "settings": self.settings,
                "tokens": [t.persisted() for t in self.tokens.values()],
                "plugins": [p.persisted() for p in self.plugins.values()],
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
        """Opens a camera's frame source.

        A failure logs at debug only: the ticker retries every few seconds,
        so per-attempt warnings would flood the tail, and the watchdog
        already raises an edge-triggered warning when a watched camera's
        outage sustains.
        """
        try:
            source = await self.platform.open_camera(camera.id, camera.source)
        except Exception as exc:
            logger.debug("camera '%s' (%s) failed to attach: %s", camera.name, camera.id, exc)
            return
        if self.cameras.get(camera.id) is not camera:
            source.close()
            await self.platform.release_camera(camera.id, camera.source)
            return
        camera.frame_source = source
        source.set_monitoring(camera.in_use)
        if source.fps > 0:
            camera.max_fps = source.fps
        logger.info("camera '%s' (%s) attached at %.1f fps", camera.name, camera.id, source.fps)

    def _schedule_attach(self, camera: Camera) -> None:
        if camera.id in self._attach_tasks:
            return
        task = asyncio.create_task(self._attach(camera))
        self._attach_tasks[camera.id] = task

        def forget(done: asyncio.Task[None]) -> None:
            if self._attach_tasks.get(camera.id) is done:
                self._attach_tasks.pop(camera.id)

        task.add_done_callback(forget)

    async def restart_camera(self, camera: Camera) -> None:
        """Releases a failed camera source and attaches it again from scratch."""
        source = camera.frame_source
        if source is None:
            return
        self.scheduler.cancel_camera(camera)
        camera.frame_source = None
        source.close()
        await self.platform.release_camera(camera.id, camera.source)
        if self.cameras.get(camera.id) is camera:
            self._schedule_attach(camera)

    async def _ticker(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(STATE_TICK_S)
            tick += 1
            for camera in self.cameras.values():
                if camera.frame_source is None:
                    if tick % REATTACH_EVERY_TICKS == 0:
                        self._schedule_attach(camera)
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
                except Exception as exc:
                    logger.warning("update check failed: %s", exc)
            await asyncio.sleep(UPDATE_CHECK_INTERVAL_S)

    async def _check_updates(self) -> None:
        """Fetches and stores the update status, raising if it cannot.

        The release history is held apart from the status the state snapshot
        carries: every changelog section together is far larger than the rest
        of the snapshot, and the UI only needs it while the update dialog is
        open.
        """
        if not self.platform.update_repo:
            raise RuntimeError("update checks are not available in this mode")
        status = await updates.fetch_updates(
            self.platform.http, self.platform.update_repo, self.platform.version, self.platform.update_asset
        )
        self.releases = status.pop("releases")
        self.update = status

    def _on_pipeline_error(self, message: str) -> None:
        self.emit({"event": "error", "message": message})

    async def _on_result(self, camera: Camera, frame: Frame, result: dict[str, Any]) -> None:
        for monitor in self.monitors.values():
            if monitor["camera_id"] != camera.id or not monitor_watching(monitor, self.printers):
                continue
            score = vision.defect_score(result, monitor["sensitivity"])
            ts = time.time()
            point = {"score": round(score, 4), "ts": ts}
            monitor_id = monitor["id"]
            self._results[monitor_id] = point
            self.history.setdefault(monitor_id, MonitorHistory()).record(ts, score, monitor["threshold"])
            emitted_at = time.monotonic()
            if emitted_at - self._result_emitted_at.get(monitor_id, 0.0) >= RESULT_EVENT_INTERVAL_S:
                self._result_emitted_at[monitor_id] = emitted_at
                self.emit(
                    {
                        "event": "result",
                        "monitor_id": monitor_id,
                        "camera_id": camera.id,
                        **point,
                        "prediction": "failure" if score >= monitor["threshold"] else "success",
                        "margin": round(result.get("margin", 0.0), 4),
                        "ms": self.scheduler.stats()["infer_ms"],
                    }
                )
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
        camera_id = uuid.uuid4().hex[:8]
        camera = Camera(
            id=camera_id,
            name=str(message.get("name") or "Camera").strip() or "Camera",
            source=source,
            max_fps=15.0,
        )
        source = await self.platform.open_camera(camera_id, camera.source)
        camera.frame_source = source
        source.set_monitoring(camera.in_use)
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
        task = self._attach_tasks.pop(camera_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
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
        except Exception as exc:
            logger.warning("printer '%s' camera listing failed: %s", printer.name, exc)
            return
        if self.printers.get(printer.id) is None:
            return
        added = False
        for descriptor in exposed:
            camera_id = f"{printer.id}-{descriptor['key']}"
            if self.cameras.get(camera_id):
                continue
            source = dict(descriptor["source"])
            camera = Camera(id=camera_id, name=descriptor["name"], source=source, printer_id=printer.id, max_fps=15.0)
            try:
                source = await self.platform.open_camera(camera_id, camera.source)
            except Exception as exc:
                logger.warning("printer camera '%s' failed to open: %s", descriptor["name"], exc)
                continue
            camera.frame_source = source
            source.set_monitoring(camera.in_use)
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
        if record["provider"] != existing.provider or record["config"] != existing.config:
            await INTEGRATIONS[existing.provider].close(existing.config)
        if record["provider"] != existing.provider:
            existing.device_state = None
            for camera in [c for c in self.cameras.values() if c.printer_id == existing.id]:
                await self._drop_camera(camera.id)
        existing.name = record["name"]
        existing.provider = record["provider"]
        existing.config = record["config"]
        asyncio.ensure_future(self.reconcile_printer_cameras(existing))

    async def _cmd_printer_remove(self, message: dict[str, Any]) -> None:
        printer = self.printers.remove(message["id"])
        if printer:
            await INTEGRATIONS[printer.provider].close(printer.config)
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
        logger.info("monitor %s registered", monitor_id)

    async def _cmd_monitor_update(self, message: dict[str, Any]) -> None:
        existing = self.monitors.get(message["id"])
        if not existing:
            raise KeyError(f"no monitor {message['id']}")
        self.monitors[message["id"]] = sanitise_monitor(message["id"], message.get("patch", {}), existing)

    async def _cmd_monitor_remove(self, message: dict[str, Any]) -> None:
        if self.monitors.pop(message["id"], None) is not None:
            logger.info("monitor %s removed", message["id"])
        self.history.pop(message["id"], None)
        self._results.pop(message["id"], None)
        self._result_emitted_at.pop(message["id"], None)

    async def _cmd_history_get(self, message: dict[str, Any]) -> None:
        history = self.history.get(message["monitor_id"])
        series = history.series() if history else {"buckets": [], "snaps": [], "alerts": [], "stats": {}}
        self.emit({"event": "history", "monitor_id": message["monitor_id"], "now": time.time(), **series, "req_id": message.get("req_id")})

    async def _cmd_snapshot_get(self, message: dict[str, Any]) -> None:
        jpeg = self.monitor_snapshot(message["monitor_id"], message["id"])
        if jpeg is None:
            raise KeyError(f"no snapshot {message['id']!r}")
        self.emit({"event": "snapshot", "id": message["id"], "jpeg": base64.b64encode(jpeg).decode(), "req_id": message.get("req_id")})

    async def _cmd_camera_snapshot(self, message: dict[str, Any]) -> None:
        """Hands back a still of a camera as it looks now.

        The frame carries the camera's own brightness, crop and rotation, so it
        is the picture the dashboard shows rather than what the source sent.
        """
        jpeg = await self.snapshot(message["camera_id"])
        if jpeg is None:
            raise KeyError(f"camera {message['camera_id']!r} has no frame to hand over")
        self.emit(
            {
                "event": "frame",
                "camera_id": message["camera_id"],
                "jpeg": base64.b64encode(jpeg).decode(),
                "req_id": message.get("req_id"),
            }
        )

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
        patch = {k: v for k, v in message.get("patch", {}).items() if k in SETTINGS_DEFAULTS}
        settings = {**self.settings, **patch}
        if settings["inference_runtime"] not in ("auto", "litert", "onnx"):
            raise ValueError("inference runtime must be auto, litert or onnx")
        if settings["inference_runtime"] != self.settings["inference_runtime"]:
            await self.scheduler.reconfigure(lambda: self.platform.configure(settings))
        self.settings = settings
        logger.info("settings updated: %s", sorted(patch))

    async def _cmd_token_create(self, message: dict[str, Any]) -> None:
        name = str(message.get("name") or "token").strip() or "token"
        record, secret = new_token(name, message.get("scope") or "read")
        token = Token(**record)
        self.tokens.add(token)
        self._broadcast({"event": "token_created", **token.public(), "token": secret, "req_id": message.get("req_id")})

    async def _cmd_token_remove(self, message: dict[str, Any]) -> None:
        self.tokens.remove(message["id"])

    async def _cmd_update_check(self, message: dict[str, Any]) -> None:
        await self._check_updates()
        self.emit({"event": "releases", "releases": self.releases, "req_id": message.get("req_id")})

    async def _cmd_update_releases(self, message: dict[str, Any]) -> None:
        if self.update is None and self.platform.update_repo:
            await self._check_updates()
        self.emit({"event": "releases", "releases": self.releases, "req_id": message.get("req_id")})

    async def _cmd_report_send(self, message: dict[str, Any]) -> None:
        try:
            await reports.send_report(
                self.platform.http,
                reports.SENTRY_DSN,
                message=str(message.get("message") or "").strip(),
                email=str(message.get("email") or "").strip() or None,
                client=message.get("client") or {},
                diag=reports.diagnostics(self),
                attachments=message.get("attachments") or [],
                ui_logs=message.get("logs") or [],
                secrets=reports.collect_secrets(self),
            )
            self.emit({"event": "report_sent", "ok": True, "req_id": message.get("req_id")})
        except Exception as exc:
            logger.warning("bug report failed to send", exc_info=True)
            self.emit({"event": "report_sent", "ok": False, "error": str(exc), "req_id": message.get("req_id")})

    async def send_alerts(self, title: str, body: str, image: bytes | None) -> None:
        """Delivers a message through every configured notification channel.

        Args:
            title: Short headline the channel shows first.
            body: The detail beneath it.
            image: JPEG snapshot to attach, where the channel carries one.
        """
        configured = {nid: config for nid, config in self.settings.get("notifiers", {}).items() if nid in NOTIFIERS}
        for notifier_id, config in configured.items():
            try:
                await NOTIFIERS[notifier_id].send(self.platform.http, config, title, body, image)
            except Exception as exc:
                logger.debug("notifier %s delivery traceback", notifier_id, exc_info=True)
                self.emit({"event": "error", "message": f"{NOTIFIERS[notifier_id].label} notification failed: {exc}"})

    async def _cmd_notify_send(self, message: dict[str, Any]) -> None:
        """Sends a caller's own message through the configured channels."""
        title = str(message.get("title") or "PrintGuard").strip()[:80]
        body = str(message.get("text", "")).strip()[:400]
        if not body:
            raise ValueError("a notification needs something to say")
        await self.send_alerts(title, body, None)

    async def _cmd_plugin_install(self, message: dict[str, Any]) -> None:
        """Fetches, verifies and registers a plugin, or reinstalls one in place.

        A plugin arrives disabled and holding nothing, since the permissions it
        asks for are accepted at the point of enabling it. Reinstalling is how a
        plugin is upgraded: the id is what identifies it, so a newer revision
        replaces the old bytes and keeps the permissions and stored data it
        already has. One that asks for more than it did stands down until the
        wider list has been accepted too.
        """
        source = dict(message.get("source") or {})
        if source.get("kind") == "github":
            manifest, sources, files, sha = await plugins.fetch_github(
                self.platform.http, str(source.get("repo", "")), str(source.get("path", "")), str(source.get("ref") or "HEAD")
            )
            source = {"kind": "github", "repo": source["repo"], "path": str(source.get("path", "")), "ref": sha}
        elif source.get("kind") == "file":
            manifest, sources, files = plugins.unpack(base64.b64decode(message["zip"]))
            source = {"kind": "file", "filename": str(source.get("filename", "") or "bundle.zip")}
        else:
            raise ValueError(f"unknown plugin source {source.get('kind')!r}")
        manifest = plugins.sanitise_manifest(manifest)
        sources = plugins.sanitise_sources(sources)
        assets = plugins.sanitise_assets(files)
        if set(manifest["assets"]) - set(assets):
            raise ValueError(f"{manifest['id']} is missing {', '.join(sorted(set(manifest['assets']) - set(assets)))}")
        digests = plugins.digests(manifest, sources, assets)
        await self._refresh_catalogue(quiet=True)
        entry = plugins.verified_by(self.catalogue, manifest["id"], digests)
        existing = self.plugins.get(manifest["id"])
        granted = [p for p in (existing.granted if existing else []) if p in manifest["permissions"]]
        self.plugins.add(
            Plugin(
                id=manifest["id"],
                manifest=manifest,
                sources=sources,
                assets=assets,
                digests=digests,
                source=source,
                granted=granted,
                config=existing.config if existing else {},
                verified=entry is not None,
                enabled=bool(existing and existing.enabled and plugins.consented(manifest, granted)),
                installed=time.time(),
            )
        )
        logger.info(
            "plugin %s v%s installed (%s, %s)",
            manifest["id"], manifest["version"], source["kind"], "verified" if entry else "unverified",
        )
        await self._reload_plugins()

    async def _cmd_plugin_remove(self, message: dict[str, Any]) -> None:
        self.plugins.remove(message["id"])
        await self._reload_plugins()

    async def _cmd_plugin_update(self, message: dict[str, Any]) -> None:
        """Applies a patch, refusing to run a plugin whose permissions stand unaccepted.

        Raises:
            PermissionError: If enabling one that asks for more than it holds.
        """
        plugin = self.plugins.get(message["id"])
        if not plugin:
            raise KeyError(f"no plugin {message['id']}")
        patch = message.get("patch", {})
        if "granted" in patch:
            plugin.granted = [p for p in patch["granted"] if p in plugin.manifest["permissions"]]
        if "enabled" in patch:
            if patch["enabled"] and not plugins.consented(plugin.manifest, plugin.granted):
                raise PermissionError(f"{plugin.id} asks for permissions that have not been accepted")
            plugin.enabled = bool(patch["enabled"])
            plugin.failure = None
        if "config" in patch:
            plugin.config = plugins.sanitise_config(patch["config"])
        if not {"config"} >= set(patch):
            await self._reload_plugins()

    async def _cmd_plugin_code(self, message: dict[str, Any]) -> None:
        plugin = self.plugins.get(message["id"])
        if not plugin:
            raise KeyError(f"no plugin {message['id']}")
        self.emit(
            {
                "event": "plugin_code",
                "id": plugin.id,
                "sources": plugin.sources,
                "assets": plugin.assets,
                "granted": plugin.granted,
                "req_id": message.get("req_id"),
            }
        )

    async def _cmd_plugin_catalogue(self, message: dict[str, Any]) -> None:
        await self._refresh_catalogue()
        self.emit({"event": "catalogue", "plugins": self.catalogue, "req_id": message.get("req_id")})

    async def _network_allows(self, plugin_id: str, url: str) -> Plugin:
        """Checks a plugin may reach a URL, and returns it for the caller to use.

        Args:
            plugin_id: Whose request it is.
            url: Where it wants to go.

        Returns:
            The plugin record.

        Raises:
            PermissionError: If the plugin holds no network grant, the URL falls
                outside every pattern it declared, or it lands on this network
                without the grant that covers that.
        """
        plugin = self.plugins.get(plugin_id)
        if not plugin or not plugin.may("net"):
            raise PermissionError("plugin may not reach the network")
        if not urls.allowed(url, plugin.manifest["urls"]):
            raise PermissionError(f"plugin {plugin.id} did not declare {url}")
        if await asyncio.to_thread(urls.resolves_local, url) and not plugin.may("net:local"):
            raise PermissionError(f"plugin {plugin.id} may not reach {url} on this network")
        return plugin

    def _within_rate(self, plugin_id: str) -> bool:
        """Whether a plugin has requests left in the current window."""
        now = time.monotonic()
        recent = [at for at in self._plugin_calls.get(plugin_id, []) if now - at < PLUGIN_RATE_WINDOW_S]
        self._plugin_calls[plugin_id] = [*recent, now]
        return len(recent) < PLUGIN_RATE_LIMIT

    async def _cmd_plugin_http(self, message: dict[str, Any]) -> None:
        """Makes an outbound request on a plugin's behalf, if it may.

        A plugin has no network of its own in either sandbox, so this is the
        only way out, and it only opens for the patterns the plugin's manifest
        declares and the user granted. The answer goes back as an ``http`` event
        tagged with whatever the plugin named the request, since a plugin runs
        and returns rather than waiting on anything.
        """
        plugin = await self._network_allows(message["id"], str(message.get("url", "")))
        if not self._within_rate(plugin.id):
            raise PermissionError(f"plugin {plugin.id} is making requests faster than {PLUGIN_RATE_LIMIT} a minute")
        await self._refresh_sign_in(plugin)
        filled = plugins.fill_secrets(
            {"url": str(message.get("url", "")), "headers": message.get("headers") or None, "json": message.get("json")},
            plugin.secrets,
        )
        status, body = await self.platform.http(
            str(message.get("method", "GET")).upper(),
            filled["url"],
            headers=filled["headers"],
            json=filled["json"],
            timeout=PLUGIN_TIMEOUT_S,
        )
        self.emit(
            {
                "event": "http",
                "id": plugin.id,
                "tag": str(message.get("tag", "")),
                "status": status,
                "body": body if isinstance(body, (dict, list)) else str(body)[:MAX_PLUGIN_BODY],
                "req_id": message.get("req_id"),
            }
        )

    async def _cmd_plugin_socket(self, message: dict[str, Any]) -> None:
        """Opens, writes to or closes a WebSocket a plugin is holding."""
        action = str(message.get("action", ""))
        plugin_id = str(message["id"])
        if action == "open":
            await self._network_allows(plugin_id, str(message.get("url", "")))
        await self.sockets.act(
            plugin_id, action, str(message.get("tag", "")), str(message.get("url", "")), str(message.get("text", ""))
        )

    def _offering(self, plugin_id: str, channel: str) -> Plugin:
        """The plugin answering on a channel, if it offers that channel at all.

        Raises:
            PermissionError: If it is not installed, not running, or offers
                nothing by that name.
        """
        plugin = self.plugins.get(plugin_id)
        if plugin is None or not plugin.enabled or not plugin.may("link:provide"):
            raise PermissionError(f"no plugin {plugin_id!r} is answering other plugins")
        if channel not in plugin.manifest["provides"]:
            raise PermissionError(f"{plugin_id} does not offer {channel!r}")
        return plugin

    async def _cmd_plugin_call(self, message: dict[str, Any]) -> None:
        """Puts one plugin's question to another, and remembers who asked.

        Both ends declared this: the caller named the plugin and channel in its
        manifest and the user accepted it, and the answering plugin offers that
        channel. Neither reaches the other on any other footing.
        """
        caller = self.plugins.get(message["id"])
        to, channel = str(message.get("to", "")), str(message.get("channel", ""))
        if not caller or not caller.may("link:consume") or f"{to}:{channel}" not in caller.manifest["consumes"]:
            raise PermissionError(f"plugin {message['id']} did not declare {to}:{channel}")
        self._offering(to, channel)
        body = plugins.sanitise_config({"body": message.get("body")})["body"]
        call_id = uuid.uuid4().hex
        now = time.monotonic()
        self._pending_calls = {k: v for k, v in self._pending_calls.items() if now - v[3] < CALL_TTL_S}
        self._pending_calls[call_id] = (caller.id, to, str(message.get("tag", "")), now)
        self.emit({"event": "call", "id": to, "from": caller.id, "channel": channel, "body": body, "call_id": call_id})

    async def _cmd_plugin_answer(self, message: dict[str, Any]) -> None:
        """Returns one plugin's answer to the plugin that asked for it."""
        waiting = self._pending_calls.pop(str(message.get("call_id", "")), None)
        if waiting is None or waiting[1] != message["id"]:
            raise PermissionError("no question of that plugin is waiting for an answer")
        caller, answering, tag, _ = waiting
        body = plugins.sanitise_config({"body": message.get("body")})["body"]
        self.emit({"event": "answer", "id": caller, "tag": tag, "from": answering, "channel": str(message.get("channel", "")), "body": body})

    async def _cmd_plugin_publish(self, message: dict[str, Any]) -> None:
        """Hands one plugin's message to everybody who asked to hear that channel."""
        channel = str(message.get("channel", ""))
        publisher = self._offering(str(message["id"]), channel)
        body = plugins.sanitise_config({"body": message.get("body")})["body"]
        for plugin in self.plugins.running():
            if plugin.may("link:consume") and f"{publisher.id}:{channel}" in plugin.manifest["consumes"]:
                self.emit({"event": "message", "id": plugin.id, "from": publisher.id, "channel": channel, "body": body})

    async def _cmd_plugin_secrets(self, message: dict[str, Any]) -> None:
        """Stores the credentials the user typed into a plugin's own form.

        Values only ever travel inwards: a plugin references them by name and
        PrintGuard fills them in as a request leaves, so neither the plugin nor
        the dashboard reads one back.
        """
        plugin = self.plugins.get(message["id"])
        if not plugin:
            raise KeyError(f"no plugin {message['id']}")
        given = message.get("secrets") or {}
        kept = plugins.sanitise_secrets(given, list(plugin.manifest["secrets"]))
        plugin.secrets = {**{name: value for name, value in plugin.secrets.items() if name.startswith("oauth")}, **kept}
        await self._reload_plugins()

    async def _cmd_plugin_oauth(self, message: dict[str, Any]) -> None:
        """Starts a plugin's sign-in, or forgets what an earlier one returned."""
        plugin = self.plugins.get(message["id"])
        if not plugin or not plugin.may("oauth"):
            raise PermissionError("plugin may not connect an account")
        if str(message.get("action")) == "forget":
            plugin.secrets = {name: value for name, value in plugin.secrets.items() if not name.startswith("oauth")}
            return
        url = self.oauth.start(plugin.id, plugin.manifest["oauth"], str(message.get("origin", "")))
        self.emit({"event": "plugin_oauth", "id": plugin.id, "url": url, "req_id": message.get("req_id")})

    async def finish_sign_in(self, state: str, code: str) -> str | None:
        """Completes a sign-in a provider has sent the user back from.

        Args:
            state: What came back on the callback.
            code: The authorisation code.

        Returns:
            The name of the plugin now signed in, or None if nothing was waiting.
        """
        plugin_id = self.oauth.waiting_for(state)
        plugin = self.plugins.get(plugin_id) if plugin_id else None
        if plugin is None:
            return None
        plugin.secrets = {**plugin.secrets, **await self.oauth.finish(state, code, plugin.manifest["oauth"])}
        logger.info("plugin %s signed in to %s", plugin.id, plugin.manifest["oauth"]["label"])
        self._broadcast(self.state_event())
        return plugin.manifest["name"]

    async def _refresh_sign_in(self, plugin: Plugin) -> None:
        """Renews a plugin's access token before a request goes out on it."""
        if not plugin.manifest["oauth"]:
            return
        renewed = await self.oauth.refreshed(plugin.manifest["oauth"], plugin.secrets)
        if renewed is not None:
            plugin.secrets = renewed

    async def _cmd_plugin_notify(self, message: dict[str, Any]) -> None:
        plugin = self.plugins.get(message["id"])
        if not plugin or not plugin.may("notify"):
            raise PermissionError("plugin may not raise notifications")
        self.emit(
            {
                "event": "plugin_notice",
                "id": plugin.id,
                "name": plugin.manifest["name"],
                "text": str(message.get("text", ""))[:200],
                "req_id": message.get("req_id"),
            }
        )

    async def _refresh_catalogue(self, quiet: bool = False) -> None:
        try:
            self.catalogue = await plugins.fetch_catalogue(self.platform.http, self.settings["catalogue_url"])
        except Exception as exc:
            if not quiet:
                raise
            logger.warning("plugin catalogue unavailable: %s", exc)

    async def _reload_plugins(self) -> None:
        """Hands the running set to the hub's plugin runtime, where there is one.

        Sockets belong to the plugin that opened them, so anything no longer
        running loses its connections rather than keeping them open behind a
        grant that has gone.
        """
        running = self.plugins.running()
        await self.sockets.drop_all({plugin.id for plugin in running})
        runtime = self.platform.plugin_runtime
        if runtime is not None:
            await runtime.reload(running)

    def plugin_failed(self, plugin_id: str, reason: str) -> None:
        """Disables a plugin its runtime could not keep running, and says why."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None or not plugin.enabled:
            return
        plugin.enabled = False
        plugin.failure = reason
        self.emit({"event": "error", "message": f"plugin {plugin.manifest['name']} stopped: {reason}"})
        self._sync()

    async def _cmd_report_bundle(self, message: dict[str, Any]) -> None:
        files = reports.report_files(
            diag=reports.diagnostics(self),
            ui_logs=message.get("logs") or [],
            secrets=reports.collect_secrets(self),
        )
        self.emit(
            {
                "event": "report_bundle",
                "filename": reports.archive_name(),
                "zip": base64.b64encode(reports.archive(files)).decode(),
                "req_id": message.get("req_id"),
            }
        )
