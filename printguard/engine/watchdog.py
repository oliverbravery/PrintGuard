"""Defect response, covering streak detection, printer actions, notifications
and the health watchdog that keeps failures loud.

Nothing in the alert path fails silently. Failed printer actions, failed
notification deliveries and dropped-out cameras or printer services all
emit protocol events, and sustained outages are pushed through the
configured notifiers so the user hears about them away from the dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Coroutine

from .integrations import INTEGRATIONS, DeviceAction, DeviceState, DeviceStatus
from .monitors import monitor_watching
from .notifiers import NOTIFIERS
from .platform import Frame

if TYPE_CHECKING:
    from .engine import Engine
    from .registry import Camera

logger = logging.getLogger(__name__)

DEVICE_POLL_S = 5.0
NOTIFY_COOLDOWN_S = 30.0
WATCH_TICK_S = 2.0
GRACE_DEFAULT_S = 120.0
GRACE_MIN_S = 30.0
GRACE_MAX_S = 900.0
REPEAT_EVERY_S = 1800.0
RESTART_AFTER_S = 15.0
RESTART_COOLDOWN_S = 60.0
RECOVER_HOLD_S = 60.0
FLAP_HOLD_MAX_S = 900.0
STALL_GRACE_S = 30.0
COVERAGE_WINDOW_S = 600.0
COVERAGE_SAMPLES = int(COVERAGE_WINDOW_S / WATCH_TICK_S)
COVERAGE_MIN = 0.9
ACT_ATTEMPTS = 3
ACT_RETRY_S = 1.0


def clamp_grace(seconds: Any) -> float:
    """Clamps the configured fault grace period to a range that stays safe.

    The floor keeps a fault from going unreported for long enough to matter and
    the ceiling stops the grace period being turned into an off switch: an
    unwatched print is the one thing the user always has to hear about.

    Args:
        seconds: The grace period the user asked for.

    Returns:
        The grace period the watchdog will actually apply.
    """
    return max(GRACE_MIN_S, min(GRACE_MAX_S, float(seconds)))


class Watchdog:
    """Watches inference scores per monitor and reacts to sustained defects."""

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_notified: dict[str, float] = {}
        self._down_since: dict[str, float] = {}
        self._healthy_since: dict[str, float] = {}
        self._flaps: dict[str, int] = {}
        self._warned: set[str] = set()
        self._last_warned: dict[str, float] = {}
        self._restarted: dict[str, float] = {}
        self._online_since: dict[str, float] = {}
        self._coverage: dict[str, deque[bool]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _schedule(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        """Cancels pending printer actions and notifications."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

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
                    snapshot = DeviceState(DeviceStatus.OFFLINE).public()
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
        """Warns when a watched camera drops out or a printer stops reporting.

        A fault has to hold for the configured grace period before it is
        announced, so the blips a wireless camera produces pass unremarked,
        and it is then repeated every REPEAT_EVERY_S for as long as it lasts,
        so an outage slept through is not announced only once. Recovery is
        announced once health has held for _recover_hold(). Re-attaching a
        failed camera is on its own timer, so lengthening the grace period
        delays the notification and never the recovery.

        A camera that stays online but stops producing fresh frames counts as
        stalled - frozen feeds must not pass for monitoring. One that keeps
        dropping and returning clears the grace period every time yet is only
        watching part of the print, so the share of the last COVERAGE_WINDOW_S
        it delivered frames for is warned on separately. Printer health is
        checked for every enabled monitor, since a printer that reports
        nothing usable is the reason its monitor is watching in the first
        place.
        """
        while True:
            now = time.monotonic()
            grace = self._engine.settings["fault_grace_s"]
            for monitor in list(self._engine.monitors.values()):
                mid = monitor["id"]
                printer = self._engine.printers.get(monitor["printer_id"]) if monitor.get("printer_id") else None
                if monitor.get("enabled") and printer is not None:
                    await self._edge(
                        f"device:{mid}",
                        printer.online,
                        now,
                        grace,
                        monitor,
                        f"Cannot tell whether the printer for '{monitor['name']}' is printing, so it keeps watching and a defect cannot pause the print",
                        f"Printer for '{monitor['name']}' is reporting its state again",
                    )
                camera = self._engine.cameras.get(monitor["camera_id"]) if monitor["camera_id"] else None
                if not monitor_watching(monitor, self._engine.printers) or camera is None:
                    self._online_since.pop(mid, None)
                    self._coverage.pop(mid, None)
                    continue
                if camera.online:
                    self._online_since.setdefault(mid, now)
                else:
                    self._online_since.pop(mid, None)
                offline_key = f"offline:{mid}"
                await self._edge(
                    offline_key,
                    camera.online,
                    now,
                    grace,
                    monitor,
                    f"Camera '{camera.name}' is offline, so '{monitor['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' is back, so '{monitor['name']}' is monitored again",
                )
                if not camera.online and self._due_restart(offline_key, now):
                    await self._engine.restart_camera(camera)
                stall_key = f"stalled:{mid}"
                progressing = (
                    camera.online and camera.last_done > self._down_since[stall_key]
                    if stall_key in self._warned
                    else not camera.online or now - max(camera.last_done, self._online_since.get(mid, now)) < STALL_GRACE_S
                )
                await self._edge(
                    stall_key,
                    progressing,
                    now,
                    grace,
                    monitor,
                    f"Camera '{camera.name}' feed has stalled, so '{monitor['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' feed recovered, so '{monitor['name']}' is monitored again",
                )
                if not progressing and self._due_restart(stall_key, now):
                    await self._engine.restart_camera(camera)
                await self._cover(monitor, camera, offline_key, now)
            await asyncio.sleep(WATCH_TICK_S)

    async def _cover(self, monitor: dict[str, Any], camera: "Camera", offline_key: str, now: float) -> None:
        """Warns when a camera has been up for too little of the recent window.

        A camera that drops for a minute every few minutes never holds a fault
        long enough to be announced, yet leaves the print unwatched for a real
        share of its run. Sampling how much of the last COVERAGE_WINDOW_S it
        delivered frames for catches that as one warning about an unreliable
        feed rather than one per drop. A window that has not filled yet says
        nothing, and an announced outage empties it, so this only ever speaks
        about drops that were too short to announce on their own.

        Args:
            monitor: The monitor the camera is bound to.
            camera: The camera being sampled.
            offline_key: Watch key for that camera's outage condition.
            now: Current monotonic time.
        """
        samples = self._coverage.setdefault(monitor["id"], deque(maxlen=COVERAGE_SAMPLES))
        if offline_key in self._warned:
            samples.clear()
        samples.append(camera.online)
        covered = sum(samples) / len(samples)
        steady = len(samples) < samples.maxlen or covered >= COVERAGE_MIN
        await self._edge(
            f"unstable:{monitor['id']}",
            steady,
            now,
            0.0,
            monitor,
            f"Camera '{camera.name}' dropped out for {(1 - covered) * 100:.0f}% of the last {COVERAGE_WINDOW_S / 60:.0f} minutes, so '{monitor['name']}' is not being monitored reliably",
            f"Camera '{camera.name}' is steady again, so '{monitor['name']}' is monitored reliably",
        )

    def _due_restart(self, key: str, now: float) -> bool:
        """Whether a faulting camera is due to be torn down and attached afresh.

        A camera source reconnects on its own, so re-attaching is the heavier
        fallback for one that has wedged rather than the first response. It
        runs on its own timer and is rate limited, so it neither waits for the
        grace period nor fires repeatedly at a camera that is flapping.

        Args:
            key: Watch key for the fault condition.
            now: Current monotonic time.

        Returns:
            Whether to re-attach, recording the attempt when it says yes.
        """
        if now - self._down_since.get(key, now) < RESTART_AFTER_S:
            return False
        if now - self._restarted.get(key, now - RESTART_COOLDOWN_S) < RESTART_COOLDOWN_S:
            return False
        self._restarted[key] = now
        return True

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
        if not healthy:
            self._healthy_since.pop(key, None)
            down_since = self._down_since.setdefault(key, now)
            if key in self._warned:
                if now - self._last_warned[key] >= REPEAT_EVERY_S:
                    await self._warn(key, monitor, down_message)
                return
            if now - down_since < grace:
                return
            self._warned.add(key)
            await self._warn(key, monitor, down_message)
            return
        healthy_since = self._healthy_since.setdefault(key, now)
        if key not in self._warned:
            self._down_since.pop(key, None)
            if now - healthy_since >= FLAP_HOLD_MAX_S:
                self._flaps.pop(key, None)
            return
        if now - healthy_since < self._recover_hold(key):
            return
        self._warned.discard(key)
        self._down_since.pop(key, None)
        self._flaps[key] = self._flaps.get(key, 0) + 1
        await self._warn(key, monitor, up_message, recovered=True)

    def _recover_hold(self, key: str) -> float:
        """How long a condition must stay healthy before its recovery is announced.

        Every recovery doubles what the next one has to prove, up to
        FLAP_HOLD_MAX_S, so a source that keeps dropping and reconnecting is
        announced once for the whole unstable episode instead of on every
        cycle. The requirement lapses once the condition has held for the
        maximum without faulting again.
        """
        return min(FLAP_HOLD_MAX_S, RECOVER_HOLD_S * 2 ** self._flaps.get(key, 0))

    async def _warn(self, key: str, monitor: dict[str, Any], message: str, recovered: bool = False) -> None:
        self._last_warned[key] = time.monotonic()
        self._engine.emit({"event": "warning", "monitor_id": monitor["id"], "message": message, "recovered": recovered})
        if monitor.get("notify"):
            self._schedule(self._engine.send_alerts(f"PrintGuard {'recovered' if recovered else 'warning'}", message, None))

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
        self._schedule(self._respond(monitor, frame, score))

    async def _respond(self, monitor: dict[str, Any], frame: Frame, score: float) -> None:
        action = await self._act(monitor)
        alert = {"score": round(score, 3), "action": action, "ts": time.time()}
        if self._streaks.get(monitor["id"], 0):
            monitor["alert"] = alert
        self._engine.emit({"event": "alert", "monitor_id": monitor["id"], **alert})
        image = await self._engine.platform.encode_jpeg(frame.rgb)
        self._engine.note_alert(monitor["id"], alert, image)
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
        logger.debug("printer action traceback for '%s'", monitor["name"], exc_info=last_error)
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
            body = f"AUTOMATIC {monitor['on_defect'].upper()} FAILED, check the printer"
        elif action == "none":
            body = "Alert only: no printer action configured"
        else:
            body = f"Action taken: {action}"
        await self._engine.send_alerts(title, body, image)

