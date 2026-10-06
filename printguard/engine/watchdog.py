"""Defect response, covering streak detection, printer actions, notifications
and the health watchdog that keeps failures loud.

Nothing in the alert path fails silently. Failed printer actions, failed
notification deliveries and dropped-out cameras or printer services all
emit protocol events, and sustained outages are pushed through the
configured notifiers so the user hears about them away from the dashboard.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Coroutine

from . import logs
from .bounds import clamp
from .integrations import INTEGRATIONS, DeviceAction, DeviceState, DeviceStatus
from .monitors import monitor_watching
from .notifiers import NOTIFIERS
from .platform import Frame
from .reviews import ENDED_STATUSES

if TYPE_CHECKING:
    from .engine import Engine
    from .registry import Camera, Printer

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
ACT_FAILED_COOLDOWN_S = 30.0
ACT_DEADLINE_S = 45.0


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
    return clamp("fault_grace_s", seconds, GRACE_MIN_S, GRACE_MAX_S)


class Watchdog:
    """Watches inference scores per monitor and reacts to sustained defects.

    Attributes:
        responding: Ids of the monitors with a defect response in flight.
    """

    def __init__(self, engine: "Engine") -> None:
        self._engine = engine
        self._streaks: dict[str, int] = {}
        self.responding: set[str] = set()
        self._cooldown_until: dict[str, float] = {}
        self._last_notified: dict[tuple[str, str], float] = {}
        self._down_since: dict[str, float] = {}
        self._healthy_since: dict[str, float] = {}
        self._flaps: dict[str, int] = {}
        self._warned: set[str] = set()
        self._last_warned: dict[str, float] = {}
        self._restarted: dict[str, float] = {}
        self._reads = itertools.count()
        self._answered: dict[str, int] = {}
        self._online_since: dict[str, float] = {}
        self._coverage: dict[str, deque[bool]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._polls: dict[str, asyncio.Task[None]] = {}

    def _schedule(self, what: str, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def finished(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            if not done.cancelled() and done.exception():
                self._engine.report_failure(what, done.exception())

        task.add_done_callback(finished)
        return task

    async def close(self) -> None:
        """Cancels pending printer actions and notifications."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def poll_devices(self) -> float:
        """Refreshes every registered printer's state.

        They are read together and each is followed as soon as it answers, so
        one that does not answer holds up nobody else's state or camera. A
        printer whose last read is still in flight is not read again, and the
        pass waits no longer than DEVICE_POLL_S for it, so a printer that takes
        long to fail does not stretch how often the others are read.

        Returns:
            Seconds until the next poll.
        """
        began = time.monotonic()
        started = []
        for printer in self._engine.printers.values():
            if printer.id not in self._polls:
                task = self._schedule("printer polling", self.refresh(printer))
                self._polls[printer.id] = task
                task.add_done_callback(functools.partial(self._poll_finished, printer.id))
                started.append(task)
        if started:
            await asyncio.wait(started, timeout=DEVICE_POLL_S)
        return max(0.0, DEVICE_POLL_S - (time.monotonic() - began))

    def _poll_finished(self, printer_id: str, task: asyncio.Task[None]) -> None:
        if self._polls.get(printer_id) is task:
            del self._polls[printer_id]

    async def refresh(self, printer: "Printer", after_command: bool = False) -> None:
        """Reads a printer and re-gates its monitors when its state changed.

        A change in the status it last reported is saved, so a hub restarted
        while the printer is switched off still knows it was idle.

        Args:
            printer: The printer to read.
            after_command: Whether this is the read that follows a command sent
                to it, which a failure leaves to the next poll instead of
                taking the printer offline.
        """
        reported = printer.reported_status
        if await self._read(printer, after_command):
            self.follow_printers()
        if printer.reported_status != reported:
            self._engine.save()

    async def _read(self, printer: "Printer", after_command: bool = False) -> bool:
        """Reads a printer's state, taking a service that cannot be reached as offline.

        A printer removed by the time its turn comes is not read, since
        reading it would open the connection its removal just closed, and one
        removed while it was answering has its answer dropped. So has one whose
        connection details were edited meanwhile, since the answer came from
        an address it no longer has, and one that lands after the answer to a
        read begun later, such as a poll still in flight when the re-read that
        follows a pause has already answered. A read that fails is logged when
        it takes the printer offline, not on every poll after that. One that
        follows a command that already went through is never taken as the
        printer being offline.

        Returns:
            Whether the state changed.
        """
        adapter = INTEGRATIONS.get(printer.provider)
        if not adapter or self._engine.printers.get(printer.id) is not printer:
            return False
        asked = (printer.provider, printer.config)
        turn = next(self._reads)
        failure: Exception | None = None
        try:
            snapshot = (await adapter.fetch_state(self._engine.service_http, printer.config)).public()
        except Exception as exc:
            if after_command:
                logger.warning("printer '%s' took a command but could not be read back: %s", printer.name, logs.describe(exc))
                return False
            failure = exc
            snapshot = DeviceState(DeviceStatus.OFFLINE).public()
        if (
            self._engine.printers.get(printer.id) is not printer
            or (printer.provider, printer.config) != asked
            or turn < self._answered.get(printer.id, 0)
        ):
            return False
        self._answered[printer.id] = turn
        changed = printer.observe(snapshot)
        if changed:
            if failure:
                logger.warning("printer '%s' could not be read: %s", printer.name, logs.describe(failure))
            self._engine.emit({"event": "device", "printer_id": printer.id, **snapshot})
        return changed

    def follow_printers(self) -> None:
        """Re-syncs which cameras are scheduled after a printer's state changed.

        Inference stops while a printer is idle or paused and resumes when it
        prints, and a monitor that stands down drops its defect streak. The
        cooldown belongs to the print that set it, so it ends once the printer
        reports that print over. A pause keeps it, so a print resumed after a
        false alarm is not paused again at once.
        """
        self._engine.cameras.sync_in_use(self._engine.monitors, self._engine.printers)
        for monitor in self._engine.monitors.values():
            if not monitor_watching(monitor, self._engine.printers):
                self.drop_streak(monitor["id"])
            printer = self._engine.printers.get(monitor.get("printer_id") or "")
            if printer and printer.reported_status in ENDED_STATUSES:
                self._cooldown_until.pop(monitor["id"], None)
        if self._engine.settle_reviews():
            self._engine.save()

    def drop_streak(self, monitor_id: str) -> None:
        """Forgets the defect frames a monitor has counted towards an alert."""
        self._streaks.pop(monitor_id, None)

    async def watch_health(self) -> float:
        """Warns when a watched camera drops out or a printer stops reporting.

        A fault has to hold for the configured grace period before it is
        announced, so the blips a wireless camera produces pass unremarked,
        and it is then repeated every REPEAT_EVERY_S for as long as it lasts,
        so an outage slept through is not announced only once. Recovery is
        announced once health has held for _recover_hold(). Re-attaching a
        failed camera is on its own timer, so lengthening the grace period
        delays the notification and never the recovery.

        A camera that stays online but stops producing fresh frames counts as
        stalled - frozen feeds must not pass for monitoring. A stall lasts
        until an inference completes again, so the watchdog's own re-attach of
        the camera neither restarts its grace period nor reads as recovery.
        A stall is not announced while its camera is offline, and an announced
        outage takes over from it, so a feed that froze and then dropped is
        reported as one fault. One that keeps dropping or freezing and
        returning clears the grace period every time yet is only watching part
        of the print, so the share of the last COVERAGE_WINDOW_S it delivered
        frames for is warned on separately. A printer that reports nothing
        usable only counts while its monitor is watching, since one switched
        off after a print leaves its monitor in standby. A monitor switched
        off or unlinked from its printer forgets that fault.

        A watching monitor whose camera is not registered is as unwatched as
        one whose camera is offline, and is warned about the same way. A
        monitor that stands down forgets its camera faults, so the next print
        starts with a full grace period.

        Returns:
            Seconds until the next check.
        """
        now = time.monotonic()
        grace = self._engine.settings["fault_grace_s"]
        for monitor in list(self._engine.monitors.values()):
            mid = monitor["id"]
            watching = monitor_watching(monitor, self._engine.printers)
            printer = self._engine.printers.get(monitor["printer_id"]) if monitor.get("printer_id") else None
            device_key = f"device:{mid}"
            if not monitor.get("enabled") or printer is None:
                self._forget(device_key)
            else:
                await self._edge(
                    device_key,
                    printer.online or not watching,
                    now,
                    grace,
                    monitor,
                    f"Cannot tell whether the printer for '{monitor['name']}' is printing, so it keeps watching and a defect cannot pause the print",
                    f"Printer for '{monitor['name']}' is reporting its state again",
                )
            camera = self._engine.cameras.get(monitor["camera_id"])
            offline_key = f"offline:{mid}"
            stall_key = f"stalled:{mid}"
            if not watching or camera is None:
                self._online_since.pop(mid, None)
                self._coverage.pop(mid, None)
                self._forget(stall_key)
                self._forget(f"unstable:{mid}")
                if watching:
                    await self._edge(
                        offline_key,
                        False,
                        now,
                        grace,
                        monitor,
                        f"'{monitor['name']}' has no camera, so it is NOT being monitored",
                        "",
                    )
                else:
                    self._forget(offline_key)
                continue
            if camera.online:
                self._online_since.setdefault(mid, now)
            else:
                self._online_since.pop(mid, None)
            await self._edge(
                offline_key,
                camera.online,
                now,
                grace,
                monitor,
                f"Camera '{camera.name}' is offline, so '{monitor['name']}' is NOT being monitored",
                f"Camera '{camera.name}' is back, so '{monitor['name']}' is monitored again",
            )
            if not camera.online and self._due_restart(offline_key, camera, now):
                await self._engine.restart_camera(camera)
            if not camera.online and offline_key in self._warned:
                self._forget(stall_key)
            progressing = (
                camera.online and self._down_since[stall_key] < camera.last_done > now - STALL_GRACE_S
                if stall_key in self._down_since
                else not camera.online or now - max(camera.last_done, self._online_since.get(mid, now)) < STALL_GRACE_S
            )
            if camera.online or stall_key in self._warned:
                await self._edge(
                    stall_key,
                    progressing,
                    now,
                    grace,
                    monitor,
                    f"Camera '{camera.name}' feed has stalled, so '{monitor['name']}' is NOT being monitored",
                    f"Camera '{camera.name}' feed recovered, so '{monitor['name']}' is monitored again",
                )
            if camera.online and not progressing and self._due_restart(stall_key, camera, now):
                await self._engine.restart_camera(camera)
            await self._cover(monitor, camera, offline_key in self._warned or stall_key in self._warned, camera.online and progressing, now)
        return WATCH_TICK_S

    def _forget(self, key: str) -> None:
        """Clears a fault condition's clocks and its announced state."""
        self._down_since.pop(key, None)
        self._healthy_since.pop(key, None)
        self._last_warned.pop(key, None)
        self._warned.discard(key)

    async def _cover(self, monitor: dict[str, Any], camera: "Camera", announced: bool, delivering: bool, now: float) -> None:
        """Warns when a camera has delivered frames for too little of the recent window.

        A camera that drops for a minute every few minutes, or freezes and
        gives one frame each time it is attached again, never holds a fault
        long enough to be announced, yet leaves the print unwatched for a real
        share of its run. Sampling how much of the last COVERAGE_WINDOW_S it
        delivered frames for catches that as one warning about an unreliable
        feed rather than one per drop. A window that has not filled yet says
        nothing, and an announced outage or stall empties it and takes over
        from an unreliable feed already warned about, so this only ever speaks
        about gaps that were too short to announce on their own. A feed is only
        called steady again while its camera is delivering frames.

        Args:
            monitor: The monitor the camera is bound to.
            camera: The camera being sampled.
            announced: Whether the camera's outage or stall has itself been warned about.
            delivering: Whether the camera is online and its feed has not stalled.
            now: Current monotonic time.
        """
        key = f"unstable:{monitor['id']}"
        samples = self._coverage.setdefault(monitor["id"], deque(maxlen=COVERAGE_SAMPLES))
        if announced:
            samples.clear()
            self._forget(key)
            return
        samples.append(delivering)
        covered = sum(samples) / len(samples)
        steady = len(samples) < samples.maxlen or covered >= COVERAGE_MIN
        await self._edge(
            key,
            steady and (delivering or key not in self._warned),
            now,
            0.0,
            monitor,
            f"Camera '{camera.name}' dropped out for {(1 - covered) * 100:.0f}% of the last {COVERAGE_WINDOW_S / 60:.0f} minutes, so '{monitor['name']}' is not being monitored reliably",
            f"Camera '{camera.name}' is steady again, so '{monitor['name']}' is monitored reliably",
        )

    def _due_restart(self, key: str, camera: "Camera", now: float) -> bool:
        """Whether a faulting camera is due to be torn down and attached afresh.

        A camera source reconnects on its own, so re-attaching is the heavier
        fallback for one that has wedged rather than the first response. It
        runs on its own timer and is rate limited per camera, so it neither
        waits for the grace period nor fires repeatedly at a camera that is
        flapping or that several monitors watch.

        Args:
            key: Watch key for the fault condition.
            camera: The camera the fault is on.
            now: Current monotonic time.

        Returns:
            Whether to re-attach, recording the attempt when it says yes.
        """
        if now - self._down_since.get(key, now) < RESTART_AFTER_S:
            return False
        restarted = self._restarted.get(camera.id)
        if restarted is not None and now - restarted < RESTART_COOLDOWN_S:
            return False
        self._restarted[camera.id] = now
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
            self._schedule(f"the warning for '{monitor['name']}'", self._engine.send_alerts(f"PrintGuard {'recovered' if recovered else 'warning'}", message, None, urgent=not recovered))

    async def on_score(self, monitor: dict[str, Any], frame: Frame, score: float) -> None:
        """Advances the defect streak for a monitor and triggers responses.

        A response still in flight is the only one a monitor has, so a defect
        frame that arrives before the printer has answered sends no second
        command.

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
        if self._streaks[mid] < monitor["consecutive"] or mid in self.responding or time.monotonic() < self._cooldown_until.get(mid, 0.0):
            return
        self._cooldown_until[mid] = time.monotonic() + monitor["cooldown_s"]
        self.responding.add(mid)
        self._schedule(f"the defect response for '{monitor['name']}'", self._respond(monitor, frame, score))

    async def _respond(self, monitor: dict[str, Any], frame: Frame, score: float) -> None:
        """Acts on the printer, announces the alert, notifies and then records it.

        The notification goes out before anything is written to disk, so a
        full disk cannot hold it back. The monitor is read again once the
        printer has answered, since an edit made meanwhile replaced its record
        and a removal means there is nothing left to alert on. A printer that
        took the command is read again without waiting for the poll, so a
        paused or cancelled print stands its monitor down before another
        defect frame can repeat the command. The print's review stays open
        for as long as its monitor is responding, so a printer read idle while
        the notifiers are still answering cannot close it before the frame
        that stopped the print is kept, and it is settled once that is done.

        The alert stays on the monitor unless a clean frame arrived while the
        printer was answering. A monitor stood down meanwhile keeps it, since
        the pause that stood it down is the one being announced, while one
        switched off meanwhile had its alert cleared and stays clear. A command the
        printer did not take is tried again after ACT_FAILED_COOLDOWN_S at the
        latest, whatever the monitor's own cooldown.
        """
        mid = monitor["id"]
        try:
            action = await self._act(monitor)
            monitor = self._engine.monitors.get(mid)
            if monitor is None:
                return
            if action == "failed":
                self._cooldown_until[mid] = min(self._cooldown_until.get(mid, 0.0), time.monotonic() + ACT_FAILED_COOLDOWN_S)
            alert = {"score": round(score, 3), "action": action, "ts": time.time()}
            if self._streaks.get(mid) != 0 and monitor["enabled"]:
                monitor["alert"] = alert
            self._engine.emit({"event": "alert", "monitor_id": mid, **alert})
            picture = await self._engine.platform.encode_jpeg(frame.rgb)
            if picture is None:
                self._engine.emit({"event": "warning", "monitor_id": mid, "message": f"The alert for '{monitor['name']}' went without a picture, since its frame could not be encoded", "recovered": False})
            await self._notify(monitor, score, action, picture)
            try:
                await self._engine.note_alert(mid, alert, frame)
            finally:
                printer = self._engine.printers.get(monitor["printer_id"])
                if action not in ("none", "failed") and printer:
                    await self.refresh(printer)
        finally:
            self.responding.discard(mid)
            if self._engine.settle_reviews():
                self._engine.save()

    async def _act(self, monitor: dict[str, Any]) -> str:
        """Sends a monitor's defect action to its printer, trying again when it is not taken.

        A printer that did not take the command is read again before the next
        try. One that is already paused, or whose print is already over, has
        nothing left to stop, so the action counts as taken. The tries share
        one deadline, ACT_DEADLINE_S on top of what the adapter says a slow
        action can take, so a printer that never answers cannot hold the alert
        back for as long as its client is willing to wait.

        Returns:
            The action taken, ``none`` when the monitor has none to take, or
            ``failed``.
        """
        wanted = monitor.get("on_defect", "none")
        printer = self._engine.printers.get(monitor.get("printer_id") or "")
        adapter = INTEGRATIONS.get(printer.provider) if printer else None
        if wanted == "none" or not adapter or printer is None:
            return "none"
        action = DeviceAction.PAUSE if wanted == "pause" else DeviceAction.CANCEL
        stopped = ENDED_STATUSES if wanted == "cancel" else (*ENDED_STATUSES, DeviceStatus.PAUSED.value)
        deadline = ACT_DEADLINE_S + adapter.slow_action_s
        last_error: Exception = TimeoutError(f"the printer did not answer within {deadline:.0f} s")
        try:
            async with asyncio.timeout(deadline):
                for _ in range(ACT_ATTEMPTS):
                    try:
                        await adapter.send(self._engine.service_http, printer.config, action)
                        return wanted
                    except Exception as exc:
                        last_error = exc
                    await self.refresh(printer)
                    if printer.online and printer.device_state["status"] in stopped:
                        return wanted
                    await asyncio.sleep(ACT_RETRY_S)
        except TimeoutError:
            pass
        logger.debug("printer action traceback for '%s'", monitor["name"], exc_info=last_error)
        self._engine.emit({"event": "error", "message": f"{monitor['name']}: automatic {wanted} failed: {logs.describe(last_error)}"})
        return "failed"

    async def _notify(self, monitor: dict[str, Any], score: float, action: str, image: bytes | None) -> None:
        """Pushes an alert, unless the same outcome was pushed in the last NOTIFY_COOLDOWN_S.

        The floor is kept per outcome, so a pause that worked is still
        announced straight after one that failed, and the reverse.
        """
        if not monitor.get("notify"):
            return
        outcome = (monitor["id"], action)
        if time.monotonic() - self._last_notified.get(outcome, 0.0) < NOTIFY_COOLDOWN_S:
            return
        self._last_notified[outcome] = time.monotonic()
        title = f"PrintGuard: {monitor['name']} defect ({score * 100:.0f}%)"
        if action == "failed":
            body = f"AUTOMATIC {monitor['on_defect'].upper()} FAILED, check the printer"
        elif action == "none":
            body = "Alert only: no printer action configured"
        else:
            body = f"Action taken: {action}"
        await self._engine.send_alerts(title, body, image)

