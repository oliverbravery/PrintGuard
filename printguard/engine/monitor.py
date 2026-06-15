"""Defect response: streak detection, device actions, notifications and
the health watchdog that keeps failures loud.

Nothing in the alert path fails silently: failed device actions, failed
notification deliveries and dropped-out cameras or printer services all
emit protocol events, and sustained outages are pushed through the
configured notifiers so the user hears about them away from the dashboard.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from .integrations import INTEGRATIONS, DeviceAction
from .notifiers import NOTIFIERS
from .platform import Frame
from .printers import printer_watching

if TYPE_CHECKING:
    from .engine import Engine

DEVICE_POLL_S = 5.0
NOTIFY_COOLDOWN_S = 30.0
WATCH_TICK_S = 2.0
OFFLINE_GRACE_S = 12.0
STALL_GRACE_S = 30.0
ACT_ATTEMPTS = 3
ACT_RETRY_S = 1.0


class Monitor:
    """Watches inference scores per printer and reacts to sustained defects."""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_notified: dict[str, float] = {}
        self._down_since: dict[str, float] = {}
        self._warned: set[str] = set()
        self._online_since: dict[str, float] = {}

    async def poll_devices(self) -> None:
        """Periodically refreshes linked printer service states.

        A state change re-syncs which cameras are scheduled, so inference
        stops while a printer is idle or paused and resumes when it prints.
        """
        while True:
            changed = False
            for printer in list(self._engine.printers.values()):
                provider = printer["device"].get("provider")
                adapter = INTEGRATIONS.get(provider) if provider else None
                if not adapter:
                    continue
                try:
                    state = await adapter.fetch_state(self._engine.platform.http, printer["device"]["config"])
                    snapshot = state.public()
                except Exception:
                    snapshot = {"status": "offline", "progress": 0.0, "job": None}
                if printer.get("device_state") != snapshot:
                    printer["device_state"] = snapshot
                    changed = True
                    if not printer_watching(printer):
                        self._streaks.pop(printer["id"], None)
                    self._engine.emit({"event": "device", "printer_id": printer["id"], **snapshot})
            if changed:
                self._engine.registry.sync_in_use(self._engine.printers)
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
            for printer in list(self._engine.printers.values()):
                pid = printer["id"]
                camera = self._engine.registry.get(printer["camera_id"]) if printer["camera_id"] else None
                if not printer_watching(printer) or camera is None:
                    self._online_since.pop(pid, None)
                    continue
                if camera.online:
                    self._online_since.setdefault(pid, now)
                else:
                    self._online_since.pop(pid, None)
                await self._edge(
                    f"offline:{pid}",
                    camera.online,
                    now,
                    OFFLINE_GRACE_S,
                    printer,
                    f"Camera '{camera.name}' is offline — '{printer['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' is back — '{printer['name']}' is monitored again",
                )
                progressing = not camera.online or now - max(camera.last_done, self._online_since.get(pid, now)) < STALL_GRACE_S
                await self._edge(
                    f"stalled:{pid}",
                    progressing,
                    now,
                    0.0,
                    printer,
                    f"Camera '{camera.name}' feed has stalled — '{printer['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' feed recovered — '{printer['name']}' is monitored again",
                )
                if printer["device"].get("provider"):
                    reachable = (printer.get("device_state") or {}).get("status") != "offline"
                    await self._edge(
                        f"device:{pid}",
                        reachable,
                        now,
                        OFFLINE_GRACE_S,
                        printer,
                        f"Printer service for '{printer['name']}' is unreachable — defects cannot pause this print",
                        f"Printer service for '{printer['name']}' is reachable again",
                    )
            await asyncio.sleep(WATCH_TICK_S)

    async def _edge(
        self,
        key: str,
        healthy: bool,
        now: float,
        grace: float,
        printer: dict[str, Any],
        down_message: str,
        up_message: str,
    ) -> None:
        if healthy:
            self._down_since.pop(key, None)
            if key in self._warned:
                self._warned.discard(key)
                await self._warn(printer, up_message, recovered=True)
            return
        since = self._down_since.setdefault(key, now)
        if now - since >= grace and key not in self._warned:
            self._warned.add(key)
            await self._warn(printer, down_message)

    async def _warn(self, printer: dict[str, Any], message: str, recovered: bool = False) -> None:
        self._engine.emit({"event": "warning", "printer_id": printer["id"], "message": message, "recovered": recovered})
        if printer.get("notify"):
            await self._send_alerts(f"PrintGuard {'recovered' if recovered else 'warning'}", message, None)

    async def on_score(self, printer: dict[str, Any], frame: Frame, score: float) -> None:
        """Advances the defect streak for a printer and triggers responses.

        Args:
            printer: The printer record the score belongs to.
            frame: The frame that produced the score, used for snapshots.
            score: Defect score in [0, 1].
        """
        pid = printer["id"]
        if score < printer["threshold"]:
            self._streaks[pid] = 0
            if printer.get("alert"):
                printer["alert"] = None
            return
        self._streaks[pid] = self._streaks.get(pid, 0) + 1
        if self._streaks[pid] < printer["consecutive"] or time.monotonic() < self._cooldown_until.get(pid, 0.0):
            return
        self._cooldown_until[pid] = time.monotonic() + printer["device"]["cooldown_s"]
        action = await self._act(printer)
        printer["alert"] = {"score": round(score, 3), "action": action, "ts": time.time()}
        self._engine.emit({"event": "alert", "printer_id": pid, **printer["alert"]})
        await self._notify(printer, frame, score, action)

    async def _act(self, printer: dict[str, Any]) -> str:
        device = printer["device"]
        wanted = device.get("on_defect", "none")
        adapter = INTEGRATIONS.get(device.get("provider") or "")
        if wanted == "none" or not adapter:
            return "none"
        action = DeviceAction.PAUSE if wanted == "pause" else DeviceAction.CANCEL
        last_error: Exception | None = None
        for _ in range(ACT_ATTEMPTS):
            try:
                await adapter.send(self._engine.platform.http, device["config"], action)
                return wanted
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(ACT_RETRY_S)
        self._engine.emit({"event": "error", "message": f"{printer['name']}: automatic {wanted} failed: {last_error}"})
        return "failed"

    async def _notify(self, printer: dict[str, Any], frame: Frame, score: float, action: str) -> None:
        if not printer.get("notify"):
            return
        if time.monotonic() - self._last_notified.get(printer["id"], 0.0) < NOTIFY_COOLDOWN_S:
            return
        self._last_notified[printer["id"]] = time.monotonic()
        title = f"PrintGuard: {printer['name']} defect ({score * 100:.0f}%)"
        if action == "failed":
            body = f"AUTOMATIC {printer['device']['on_defect'].upper()} FAILED — check the printer"
        elif action == "none":
            body = "No automatic action configured"
        else:
            body = f"Action taken: {action}"
        image = await self._engine.platform.encode_jpeg(frame.rgb)
        await self._send_alerts(title, body, image)

    async def _send_alerts(self, title: str, body: str, image: bytes | None) -> None:
        configured = {nid: config for nid, config in self._engine.settings.get("notifiers", {}).items() if nid in NOTIFIERS}
        for notifier_id, config in configured.items():
            try:
                await NOTIFIERS[notifier_id].send(self._engine.platform.http, config, title, body, image)
            except Exception as exc:
                self._engine.emit({"event": "error", "message": f"{NOTIFIERS[notifier_id].label} notification failed: {exc}"})
