"""Defect response: streak detection, device actions and notifications."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from .integrations import INTEGRATIONS, DeviceAction
from .platform import Frame

if TYPE_CHECKING:
    from .engine import Engine

DEVICE_POLL_S = 5.0
NOTIFY_COOLDOWN_S = 30.0


class Monitor:
    """Watches inference scores per printer and reacts to sustained defects."""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_notified: dict[str, float] = {}

    async def poll_devices(self) -> None:
        """Periodically refreshes linked printer service states."""
        while True:
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
                    self._engine.emit({"event": "device", "printer_id": printer["id"], **snapshot})
            await asyncio.sleep(DEVICE_POLL_S)

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
        try:
            await adapter.send(self._engine.platform.http, device["config"], action)
            return wanted
        except Exception:
            return "failed"

    async def _notify(self, printer: dict[str, Any], frame: Frame, score: float, action: str) -> None:
        url = str(self._engine.settings.get("ntfy_url") or "").strip()
        if not printer.get("notify") or not url:
            return
        if time.monotonic() - self._last_notified.get(printer["id"], 0.0) < NOTIFY_COOLDOWN_S:
            return
        self._last_notified[printer["id"]] = time.monotonic()
        title = f"PrintGuard: {printer['name']} defect ({score * 100:.0f}%)"
        body = f"Action taken: {action}" if action != "none" else "No automatic action configured"
        headers = {"Title": title, "Priority": "urgent", "Tags": "rotating_light"}
        try:
            jpeg = await self._engine.platform.encode_jpeg(frame.rgb)
            if jpeg:
                headers["Filename"] = "snapshot.jpg"
                headers["Message"] = body
                await self._engine.platform.http("PUT", url, headers=headers, data=jpeg, timeout=15.0)
            else:
                await self._engine.platform.http("POST", url, headers=headers, data=body.encode(), timeout=15.0)
        except Exception:
            pass
