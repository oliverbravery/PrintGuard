"""Defect response: streak detection, printer actions, notifications and
the health watchdog that keeps failures loud.

Nothing in the alert path fails silently: failed printer actions, failed
notification deliveries and dropped-out cameras or printer services all
emit protocol events, and sustained outages are pushed through the
configured notifiers so the user hears about them away from the dashboard.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from .integrations import INTEGRATIONS, DeviceAction
from .monitors import monitor_watching
from .notifiers import NOTIFIERS
from .platform import Frame

if TYPE_CHECKING:
    from .engine import Engine

DEVICE_POLL_S = 5.0
NOTIFY_COOLDOWN_S = 30.0
WATCH_TICK_S = 2.0
OFFLINE_GRACE_S = 12.0
STALL_GRACE_S = 30.0
ACT_ATTEMPTS = 3
ACT_RETRY_S = 1.0


class Watchdog:
    """Watches inference scores per monitor and reacts to sustained defects."""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_notified: dict[str, float] = {}
        self._down_since: dict[str, float] = {}
        self._warned: set[str] = set()
        self._online_since: dict[str, float] = {}

    async def poll_devices(self) -> None:
        """Periodically refreshes registered printer states.

        A state change re-syncs which cameras are scheduled, so inference
        stops while a printer is idle or paused and resumes when it prints.
        """
        while True:
            changed = False
            for printer in self._engine.printers.values():
                adapter = INTEGRATIONS.get(printer.provider)
                if not adapter:
                    continue
                try:
                    state = await adapter.fetch_state(self._engine.platform.http, printer.config)
                    snapshot = state.public()
                except Exception:
                    snapshot = {"status": "offline", "progress": 0.0, "job": None}
                if printer.device_state != snapshot:
                    printer.device_state = snapshot
                    changed = True
                    self._engine.emit({"event": "device", "printer_id": printer.id, **snapshot})
            if changed:
                self._engine.cameras.sync_in_use(self._engine.monitors, self._engine.printers)
                for monitor in self._engine.monitors.values():
                    if not monitor_watching(monitor, self._engine.printers):
                        self._streaks.pop(monitor["id"], None)
            await asyncio.sleep(DEVICE_POLL_S)

    async def watch_health(self) -> None:
        """Warns when a watched camera or printer service drops out.

        Outages shorter than the grace period are ignored so reconnecting
        sources do not flap; each sustained outage warns exactly once and
        announces its recovery. A camera that stays online but stops
        producing fresh frames counts as stalled — frozen feeds must not
        pass for monitoring.
        """
        while True:
            now = time.monotonic()
            for monitor in list(self._engine.monitors.values()):
                mid = monitor["id"]
                camera = self._engine.cameras.get(monitor["camera_id"]) if monitor["camera_id"] else None
                if not monitor_watching(monitor, self._engine.printers) or camera is None:
                    self._online_since.pop(mid, None)
                    continue
                if camera.online:
                    self._online_since.setdefault(mid, now)
                else:
                    self._online_since.pop(mid, None)
                await self._edge(
                    f"offline:{mid}",
                    camera.online,
                    now,
                    OFFLINE_GRACE_S,
                    monitor,
                    f"Camera '{camera.name}' is offline — '{monitor['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' is back — '{monitor['name']}' is monitored again",
                )
                progressing = not camera.online or now - max(camera.last_done, self._online_since.get(mid, now)) < STALL_GRACE_S
                await self._edge(
                    f"stalled:{mid}",
                    progressing,
                    now,
                    0.0,
                    monitor,
                    f"Camera '{camera.name}' feed has stalled — '{monitor['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' feed recovered — '{monitor['name']}' is monitored again",
                )
                printer = self._engine.printers.get(monitor["printer_id"]) if monitor.get("printer_id") else None
                if printer is not None:
                    reachable = (printer.device_state or {}).get("status") != "offline"
                    await self._edge(
                        f"device:{mid}",
                        reachable,
                        now,
                        OFFLINE_GRACE_S,
                        monitor,
                        f"Printer service for '{monitor['name']}' is unreachable — defects cannot pause this print",
                        f"Printer service for '{monitor['name']}' is reachable again",
                    )
            await asyncio.sleep(WATCH_TICK_S)

    async def _edge(
        self,
        key: str,
        healthy: bool,
        now: float,
        grace: float,
        monitor: dict[str, Any],
        down_message: str,
        up_message: str,
    ) -> None:
        if healthy:
            self._down_since.pop(key, None)
            if key in self._warned:
                self._warned.discard(key)
                await self._warn(monitor, up_message, recovered=True)
            return
        since = self._down_since.setdefault(key, now)
        if now - since >= grace and key not in self._warned:
            self._warned.add(key)
            await self._warn(monitor, down_message)

    async def _warn(self, monitor: dict[str, Any], message: str, recovered: bool = False) -> None:
        self._engine.emit({"event": "warning", "monitor_id": monitor["id"], "message": message, "recovered": recovered})
        if monitor.get("notify"):
            await self._send_alerts(f"PrintGuard {'recovered' if recovered else 'warning'}", message, None)

    async def on_score(self, monitor: dict[str, Any], frame: Frame, score: float) -> None:
        """Advances the defect streak for a monitor and triggers responses.

        Args:
            monitor: The monitor record the score belongs to.
            frame: The frame that produced the score, used for snapshots.
            score: Defect score in [0, 1].
        """
        mid = monitor["id"]
        if score < monitor["threshold"]:
            self._streaks[mid] = 0
            if monitor.get("alert"):
                monitor["alert"] = None
            return
        self._streaks[mid] = self._streaks.get(mid, 0) + 1
        if self._streaks[mid] < monitor["consecutive"] or time.monotonic() < self._cooldown_until.get(mid, 0.0):
            return
        self._cooldown_until[mid] = time.monotonic() + monitor["cooldown_s"]
        action = await self._act(monitor)
        monitor["alert"] = {"score": round(score, 3), "action": action, "ts": time.time()}
        self._engine.emit({"event": "alert", "monitor_id": mid, **monitor["alert"]})
        image = await self._engine.platform.encode_jpeg(frame.rgb)
        self._engine.note_alert(mid, monitor["alert"], image)
        await self._notify(monitor, score, action, image)

    async def _act(self, monitor: dict[str, Any]) -> str:
        wanted = monitor.get("on_defect", "none")
        printer = self._engine.printers.get(monitor.get("printer_id") or "")
        adapter = INTEGRATIONS.get(printer.provider) if printer else None
        if wanted == "none" or not adapter or printer is None:
            return "none"
        action = DeviceAction.PAUSE if wanted == "pause" else DeviceAction.CANCEL
        last_error: Exception | None = None
        for _ in range(ACT_ATTEMPTS):
            try:
                await adapter.send(self._engine.platform.http, printer.config, action)
                return wanted
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(ACT_RETRY_S)
        self._engine.emit({"event": "error", "message": f"{monitor['name']}: automatic {wanted} failed: {last_error}"})
        return "failed"

    async def _notify(self, monitor: dict[str, Any], score: float, action: str, image: bytes | None) -> None:
        if not monitor.get("notify"):
            return
        if time.monotonic() - self._last_notified.get(monitor["id"], 0.0) < NOTIFY_COOLDOWN_S:
            return
        self._last_notified[monitor["id"]] = time.monotonic()
        title = f"PrintGuard: {monitor['name']} defect ({score * 100:.0f}%)"
        if action == "failed":
            body = f"AUTOMATIC {monitor['on_defect'].upper()} FAILED — check the printer"
        elif action == "none":
            body = "No automatic action configured"
        else:
            body = f"Action taken: {action}"
        await self._send_alerts(title, body, image)

    async def _send_alerts(self, title: str, body: str, image: bytes | None) -> None:
        configured = {nid: config for nid, config in self._engine.settings.get("notifiers", {}).items() if nid in NOTIFIERS}
        for notifier_id, config in configured.items():
            try:
                await NOTIFIERS[notifier_id].send(self._engine.platform.http, config, title, body, image)
            except Exception as exc:
                self._engine.emit({"event": "error", "message": f"{NOTIFIERS[notifier_id].label} notification failed: {exc}"})
