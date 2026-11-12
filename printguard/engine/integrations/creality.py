"""Creality integration over the local WebSocket of the printer's stock firmware.

Creality's Klipper-based firmware on the K1, K2, Ender-3 V3 and Hi series and
the CR-10 SE serves the WebSocket Creality Print's device manager talks to, on
port 9999 with no password. A new connection is sent the printer's whole state
and then only what changes, so one is held per printer and its frames are
merged into one report. Besides its state the printer sends a bare ``ok`` and
a ``heart_beat`` frame, which is answered with ``ok``. Nothing answers a
command, so one is taken once the printer reports the state or target it leads
to.

A sliced file is uploaded over HTTP on port 80 and started from the path the
printer's file list gives it, since that differs between models.

Protocol reference, with the state codes, commands, upload and file list:
https://github.com/CrealityOfficial/CrealityPrint/tree/v7.3.0/resources/web/deviceMgr
The heartbeat, the request that wakes a quiet connection and the frame size
mirror ha_creality_ws:
https://github.com/3dg1luk43/ha_creality_ws/blob/main/custom_components/ha_creality_ws/ws_client.py
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from ..adapters import multipart_form
from .base import DeviceAction, DeviceState, DeviceStatus, Heater, HttpFn, IntegrationAdapter, require_reply

_PORT = 9999
_CAMERA_PORT = 8080
_CONNECT_TIMEOUT_S = 5.0
_COMMAND_TIMEOUT_S = 10.0
_FILE_LIST_TIMEOUT_S = 15.0
_START_TIMEOUT_S = 30.0
_UPLOAD_TIMEOUT_S = 180.0
_QUIET_S = 10.0
"""How long a connection goes without a frame before the printer is asked for one."""
_SILENCE_LIMIT_S = 20.0
"""How long a connection goes without a frame before it is taken as dead, Creality Print's own read timeout."""
_MAX_FRAME_BYTES = 16 * 2**20
"""The largest frame read. The file list arrives as one frame of about 150 KiB for every 200 files."""
_WAKE = {"method": "get", "params": {"ReqPrinterPara": 1}}
_FILE_LIST = {"method": "get", "params": {"reqGcodeFile": 1}}
_STATUS = {
    0: DeviceStatus.IDLE,
    1: DeviceStatus.PRINTING,
    2: DeviceStatus.IDLE,
    3: DeviceStatus.IDLE,
    4: DeviceStatus.IDLE,
    5: DeviceStatus.PAUSED,
}
"""Creality Print's idle, printing, complete, failed, aborted and paused.

Pausing (6), stopping (7), restoring (8) and starting (9) say nothing of where
the print ends up.
"""
_IDLE_STATES = {code for code, status in _STATUS.items() if status is DeviceStatus.IDLE}
_ACTIONS = {
    DeviceAction.PAUSE: ({"pause": 1}, {5, 6}),
    DeviceAction.RESUME: ({"pause": 0}, {1, 8}),
    DeviceAction.CANCEL: ({"stop": 1}, {*_IDLE_STATES, 7}),
}
"""Each action's parameters and the states that show the printer took it."""
_HEATERS: dict[str, tuple[str, Callable[[int], dict[str, Any]]]] = {
    "nozzle": ("targetNozzleTemp", lambda degrees: {"nozzleTempControl": degrees}),
    "bed": ("targetBedTemp0", lambda degrees: {"bedTempControl": {"num": 0, "val": degrees}}),
}
"""Each heater's reported target and the parameters that set it."""

Report = dict[str, Any]


class _Session:
    """One WebSocket to a printer and the report merged from its frames."""

    def __init__(self, socket: ClientConnection) -> None:
        self.report: Report = {}
        self._socket = socket
        self._heard_at = time.monotonic()
        self._changed = asyncio.Condition()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, host: str) -> _Session:
        """Connects and waits for the printer's state.

        Args:
            host: The printer's address.

        Returns:
            The connection, with the printer's whole state in its report.

        Raises:
            OSError: If the printer cannot be reached.
            TimeoutError: If it does not finish the handshake in time.
            RuntimeError: If something answers on the port but sends no state.
        """
        socket = await connect(
            f"ws://{host}:{_PORT}", open_timeout=_CONNECT_TIMEOUT_S, close_timeout=1, ping_interval=None, max_size=_MAX_FRAME_BYTES
        )
        session = cls(socket)
        try:
            await session.until(lambda report: "state" in report, _CONNECT_TIMEOUT_S)
        except TimeoutError:
            await session.close()
            raise RuntimeError(f"{host}:{_PORT} answered but sent no printer state") from None
        except BaseException:
            await session.close()
            raise
        return session

    def lost(self) -> bool:
        """Whether the connection closed or the printer has gone silent on it."""
        return self._reader.done() or time.monotonic() - self._heard_at > _SILENCE_LIMIT_S

    async def wake(self) -> None:
        """Asks a printer that has gone quiet for its parameters, which it answers with a frame."""
        if time.monotonic() - self._heard_at > _QUIET_S:
            await self.send(_WAKE)

    async def send(self, message: dict[str, Any]) -> None:
        """Sends one request.

        Args:
            message: The request, a ``get`` or ``set`` method and its parameters.

        Raises:
            ConnectionError: If the connection has closed.
        """
        try:
            await self._socket.send(json.dumps(message, separators=(",", ":")))
        except ConnectionClosed as exc:
            raise ConnectionError("Creality printer closed the connection") from exc

    async def until(self, done: Callable[[Report], bool], timeout: float) -> None:
        """Waits for the report to pass a check.

        Args:
            done: The check, given the merged report.
            timeout: Seconds to wait.

        Raises:
            TimeoutError: If the report does not pass in time.
            ConnectionError: If the connection closes first.
        """
        async with asyncio.timeout(timeout), self._changed:
            await self._changed.wait_for(lambda: done(self.report) or self._reader.done())
        if not done(self.report):
            raise ConnectionError("Creality printer closed the connection")

    async def close(self) -> None:
        """Closes the connection and waits for its reader to finish."""
        await self._socket.close()
        await self._reader

    async def _read(self) -> None:
        """Merges each state frame into the report, skipping any frame that is not a JSON object."""
        try:
            async for frame in self._socket:
                self._heard_at = time.monotonic()
                try:
                    payload = json.loads(frame)
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("ModeCode") == "heart_beat":
                    await self._socket.send("ok")
                    continue
                self.report.update(payload)
                async with self._changed:
                    self._changed.notify_all()
        except ConnectionClosed:
            pass
        finally:
            async with self._changed:
                self._changed.notify_all()


class CrealityAdapter(IntegrationAdapter):
    """Talks to a Creality printer on stock firmware over its local WebSocket."""

    id = "creality"
    label = "Creality"
    docs_url = "https://github.com/CrealityOfficial/CrealityPrint/tree/v7.3.0/resources/web/deviceMgr"
    setup_hint = (
        "Works with the K1, K2, Ender-3 V3, Hi and CR-10 SE on stock firmware. The printer has no password, "
        "so keep it on a network you trust. A rooted printer running Moonraker connects as Klipper."
    )
    experimental = True
    formats = ("gcode",)
    heater_control = True
    slow_action_s = _COMMAND_TIMEOUT_S
    schema = {
        "type": "object",
        "properties": {"host": {"type": "string", "title": "Printer IP or hostname", "placeholder": "192.168.1.90"}},
        "required": ["host"],
    }

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Normalises the printer's merged report.

        Pausing, stopping, restoring and starting read as unknown, so the last
        answer stands. A failed or aborted job leaves the printer as ready for
        the next as a finished one, so all three read as idle. The printer's
        error code is not read, since it can stay set after the fault clears.
        """
        session = await self._session(config)
        await session.wake()
        report = session.report
        remaining = report.get("printLeftTime")
        return DeviceState(
            _STATUS.get(report.get("state"), DeviceStatus.UNKNOWN),
            float(report.get("printProgress") or 0.0),
            _job(report) or None,
            remaining_s=max(0, round(float(remaining))) if remaining is not None else None,
            nozzle=Heater.reported(report.get("nozzleTemp"), report.get("targetNozzleTemp")),
            bed=Heater.reported(report.get("bedTemp0"), report.get("targetBedTemp0")),
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Pauses, resumes or stops the print and waits for the printer to take it.

        A printer already in a state the action leads to is sent nothing.

        Raises:
            RuntimeError: If there is no print to pause or resume, or the
                printer does not report taking the action in time.
        """
        params, taken = _ACTIONS[action]
        session = await self._session(config)
        if session.report.get("state") in taken:
            return
        if session.report.get("state") in _IDLE_STATES:
            raise RuntimeError(f"Creality printer has no print to {action.value}")
        await _set(session, params, lambda report: report.get("state") in taken, f"the {action.value}", _COMMAND_TIMEOUT_S)

    async def heat(self, http: HttpFn, config: dict[str, Any], heater: str, target: float) -> None:
        """Sets a heater target in whole degrees, the way the printer takes it, and waits for the printer to report it.

        Raises:
            RuntimeError: If the printer does not report the target in time.
        """
        key, params = _HEATERS[heater]
        degrees = round(target)
        session = await self._session(config)
        if _number(session.report.get(key)) == degrees:
            return
        await _set(session, params(degrees), lambda report: _number(report.get(key)) == degrees, f"the {heater} target of {degrees} °C", _COMMAND_TIMEOUT_S)

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Uploads sliced G-code over HTTP and starts it from the path the printer lists it under.

        The file is matched by name and size, so a file cut short is never
        started. It starts the way Creality Print starts a print without a
        calibration first, and counts as started once the printer reports
        printing it.

        Raises:
            RuntimeError: If the printer refuses the upload, does not list the
                file, or does not start it in time.
        """
        headers, body = multipart_form({}, "file", filename, data, "application/octet-stream")
        status, _ = await http(
            "POST", f"http://{self.connection_key(config)}/upload/{filename}", headers=headers, data=body, timeout=_UPLOAD_TIMEOUT_S
        )
        require_reply("Creality printer", filename, status, status == 200)
        session = await self._session(config)
        session.report.pop("retGcodeFileInfo2", None)
        session.report.pop("retGcodeFileInfo", None)
        await session.send(_FILE_LIST)
        try:
            await session.until(lambda report: _listed(report, filename, len(data)) is not None, _FILE_LIST_TIMEOUT_S)
        except TimeoutError:
            raise RuntimeError(f"Creality printer did not list {filename} after it was uploaded") from None
        await _set(
            session,
            {"opGcodeFile": f"printprt:{_listed(session.report, filename, len(data))}", "enableSelfTest": 0},
            lambda report: report.get("state") not in _IDLE_STATES and _job(report) == filename,
            f"the print of {filename}",
            _START_TIMEOUT_S,
        )

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Exposes the MJPEG stream on port 8080 where the printer's snapshot answers.

        K1 firmware before 1.3.5.22 serves it, as does an add-on camera on the
        K1 SE or Ender-3 V3. The K2, the Hi and later K1 firmware stream WebRTC
        with Creality's own signalling, which the hub cannot read.
        """
        base = f"http://{self.connection_key(config)}:{_CAMERA_PORT}/"
        try:
            status, _ = await http("GET", f"{base}?action=snapshot", binary=True, timeout=_CONNECT_TIMEOUT_S)
        except httpx.TransportError:
            return []
        if status != 200:
            return []
        return [{"key": "camera", "name": "Creality camera", "source": {"kind": "url", "url": f"{base}?action=stream"}}]

    async def close(self, config: dict[str, Any] | None = None) -> None:
        """Closes one printer's connection, or every connection."""
        hosts = [self.connection_key(config)] if config is not None else list(self._sessions)
        for host in hosts:
            async with self._session_locks.setdefault(host, asyncio.Lock()):
                if session := self._sessions.pop(host, None):
                    await session.close()

    def connection_key(self, config: dict[str, Any]) -> str:
        """A connection is one printer's address."""
        return str(config.get("host", ""))

    async def _session(self, config: dict[str, Any]) -> _Session:
        """Returns the printer's connection, opening one when there is none or it was lost."""
        host = self.connection_key(config)
        async with self._session_locks.setdefault(host, asyncio.Lock()):
            session = self._sessions.get(host)
            if session is not None and session.lost():
                await self._sessions.pop(host).close()
                session = None
            if session is None:
                session = self._sessions[host] = await _Session.open(host)
            return session


async def _set(session: _Session, params: dict[str, Any], taken: Callable[[Report], bool], what: str, timeout: float) -> None:
    """Sends a command and waits for the report to show the printer took it.

    Args:
        session: The printer's connection.
        params: The command's parameters.
        taken: The check that shows the printer took it.
        what: The command, for the error.
        timeout: Seconds the printer has to take it.

    Raises:
        RuntimeError: If the report does not show it taken in time.
    """
    await session.send({"method": "set", "params": params})
    try:
        await session.until(taken, timeout)
    except TimeoutError:
        raise RuntimeError(f"Creality printer did not take {what} within {timeout:g} s") from None


def _job(report: Report) -> str:
    """The file name of the printer's current or last job, without its folder."""
    return str(report.get("printFileName") or "").rsplit("/", 1)[-1]


def _number(value: Any) -> float | None:
    """A number the printer reports, which it sends as text as often as not."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _listed(report: Report, filename: str, size: int) -> str | None:
    """The path the printer's file list gives a file of this name and size.

    Current firmware lists files as objects under ``retGcodeFileInfo2``, older
    firmware as ``folder:name:size`` rows in the string under
    ``retGcodeFileInfo``.

    Args:
        report: The merged report.
        filename: The file's name.
        size: Its length in bytes.

    Returns:
        The path, or None while the report holds no list naming the file at that size.
    """
    for entry in report.get("retGcodeFileInfo2") or []:
        if entry.get("name") == filename and _number(entry.get("file_size", entry.get("size"))) == size:
            return entry.get("path")
    for row in str((report.get("retGcodeFileInfo") or {}).get("fileInfo") or "").split(";"):
        folder, name, listed_size, *_ = [*row.split(":"), "", ""]
        if name == filename and _number(listed_size) == size:
            return f"{folder}/{name}"
    return None
