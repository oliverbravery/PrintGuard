"""Read stock CR-10 SE status and confirm controls over its LAN socket.

Protocol source: Creality Print 7.3 resources/web/deviceMgr. The installed
frontend sends pause:1 to pause and pause:0 to resume. State 5 is PAUSED,
state 1 is PRINTING, and 6/8 are PAUSING/RESTORING. Heater targets use
nozzleTempControl and bedTempControl (bed number 0). Cancel uses stop:1.
Sliced G-code is uploaded over HTTP and started by opGcodeFile, without rooting.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

from httpx import TransportError
from websockets.asyncio.client import ClientConnection, connect

from .base import (
    DeviceAction,
    DeviceState,
    DeviceStatus,
    Heater,
    HttpFn,
    IntegrationAdapter,
)

FETCH_TIMEOUT_S = 4.0
ACTION_TIMEOUT_S = 10.0
RESUME_TIMEOUT_S = 90.0
HEAT_TIMEOUT_S = 10.0
CANCEL_TIMEOUT_S = 90.0
UPLOAD_TIMEOUT_S = 180.0
FILE_TIMEOUT_S = 15.0
START_TIMEOUT_S = 90.0
HEATER_LIMITS = {"nozzle": 300.0, "bed": 110.0}
HEATER_FIELDS = {
    "nozzle": ("nozzleTemp", "targetNozzleTemp", "maxNozzleTemp"),
    "bed": ("bedTemp0", "targetBedTemp0", "maxBedTemp"),
}
EXPECTED_MODEL = "F003"
PAUSE_MESSAGE = '{"method":"set","params":{"pause":1}}'
RESUME_MESSAGE = '{"method":"set","params":{"pause":0}}'
CANCEL_MESSAGE = '{"method":"set","params":{"stop":1}}'
FILES_MESSAGE = '{"method":"get","params":{"reqGcodeFile":1}}'
GCODE_ROOT = "/usr/data/printer_data/gcodes/"
STATUS = {
    0: DeviceStatus.IDLE,
    1: DeviceStatus.PRINTING,
    2: DeviceStatus.IDLE,
    3: DeviceStatus.ERROR,
    4: DeviceStatus.IDLE,
    5: DeviceStatus.PAUSED,
}


def endpoint(config: dict[str, Any]) -> str:
    """Build the explicitly configured LAN endpoint, without URL credentials."""
    address = ipaddress.ip_address(str(config.get("host", "")).strip())
    if address.is_unspecified or address.is_multicast:
        raise ValueError("Use the printer's individual IP address")
    raw_port = str(config.get("port") or "9999")
    if not raw_port.isdecimal() or not 1 <= int(raw_port) <= 65535:
        raise ValueError("The WebSocket port must be between 1 and 65535")
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"ws://{host}:{int(raw_port)}/"


def state_code(value: Any) -> int | None:
    """Accept a whole numeric state or its decimal spelling, never booleans."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def normalise(raw: dict[str, Any]) -> DeviceState:
    """Map a fresh F003 report, retaining unfamiliar transitions as unknown."""
    if raw.get("model") != EXPECTED_MODEL:
        raise RuntimeError("The endpoint did not identify the expected CR-10 SE (F003)")
    code = state_code(raw.get("state"))
    status = STATUS.get(code, DeviceStatus.UNKNOWN)
    if raw.get("connect") == 0:
        status = DeviceStatus.OFFLINE
    remaining = raw.get("printLeftTime")
    return DeviceState(
        status,
        float(raw.get("printProgress") or 0),
        str(raw["printFileName"]).replace("\\", "/").rsplit("/", 1)[-1]
        if raw.get("printFileName")
        else None,
        remaining_s=max(0, int(remaining)) if remaining is not None else None,
        nozzle=Heater.reported(raw.get("nozzleTemp"), raw.get("targetNozzleTemp")),
        bed=Heater.reported(raw.get("bedTemp0"), raw.get("targetBedTemp0")),
    )


async def update(socket: ClientConnection) -> dict[str, Any]:
    """Read one flat status push; a control acknowledgement is not a state."""
    value = json.loads(await socket.recv())
    if not isinstance(value, dict):
        raise RuntimeError("The printer returned a malformed status message")
    return value


async def snapshot(socket: ClientConnection) -> dict[str, Any]:
    """Wait for model and state on this new connection without sending a query."""
    raw: dict[str, Any] = {}
    while True:
        raw.update(await update(socket))
        if "model" in raw and raw["model"] != EXPECTED_MODEL:
            raise RuntimeError("Unexpected printer model; no command was sent")
        if "model" in raw and "state" in raw:
            normalise(raw)
            return raw


def require_normal_resume(raw: dict[str, Any]) -> None:
    """Reject power-loss recovery and the SD-card block used by Creality Print."""
    if raw.get("repoPlrStatus") not in (None, 0, "0", False):
        raise RuntimeError(
            "Power-loss recovery requires the printer screen; normal resume was not confirmed"
        )
    features = raw.get("features", [])
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except ValueError:
            features = features.split(",")
    if isinstance(features, list) and "printInfo.sdCardGuardV2" in features:
        if raw.get("sdCardResumeBlocked") is True or state_code(
            raw.get("sdCardStatus")
        ) in (0, 2):
            raise RuntimeError(
                "The printer's SD-card guard blocks resume; check the printer screen"
            )


def heater_target(heater: str, target: float) -> float:
    """Validate a numeric target against the stock CR-10 SE's published limits."""
    if heater not in HEATER_LIMITS:
        raise ValueError(
            "The CR-10 SE supports only nozzle and bed temperature targets"
        )
    if isinstance(target, bool) or not isinstance(target, (int, float)):
        raise ValueError(f"The {heater} target must be a finite number")
    try:
        value = float(target)
    except OverflowError:
        raise ValueError(f"The {heater} target must be a finite number") from None
    if not math.isfinite(value) or not 0 <= value <= HEATER_LIMITS[heater]:
        raise ValueError(
            f"The {heater} target must be between 0 and {HEATER_LIMITS[heater]:g} C"
        )
    return value


def reported_number(value: Any) -> float | None:
    """Read a finite numeric status value, allowing the firmware's numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def require_idle(raw: dict[str, Any]) -> None:
    """Refuse a new job unless fresh stock telemetry positively reports idle."""
    if normalise(raw).status != DeviceStatus.IDLE:
        raise RuntimeError("The printer is not idle; no new print command sent")
    if raw.get("repoPlrStatus") not in (None, 0, "0", False):
        raise RuntimeError(
            "Power-loss recovery is pending; check the printer screen before starting a new job"
        )


def upload_name(filename: str, data: bytes) -> str:
    """Validate plain G-code and give each transfer a distinct safe filename.

    Raises:
        ValueError: If the filename is unsafe or the file is empty or binary.
    """
    if not isinstance(filename, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._ -]{0,119}\.gcode", filename
    ):
        raise ValueError(
            "Upload a .gcode file with a plain filename, without paths or special characters"
        )
    if (
        not isinstance(data, bytes)
        or not data
        or b"\x00" in data
        or data.startswith(b"PK\x03\x04")
    ):
        raise ValueError("Upload a non-empty plain-text .gcode file")
    return f"PG_{uuid.uuid4().hex[:12]}.gcode"


def upload_form(
    base_url: str, filename: str, data: bytes
) -> tuple[dict[str, str], bytes]:
    """Match the browser-style request accepted by this stock F003 printer.

    The body is buffered, using one additional file-sized buffer. The request
    matches the stock web interface and has been verified on the CR-10 SE.
    """
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    body = b"".join((head, data, f"\r\n--{boundary}--\r\n".encode()))
    return {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "Accept": "application/json, text/plain, */*",
        "Origin": base_url,
        "Referer": base_url + "/",
        "Connection": "close",
    }, body


def listed_file(change: dict[str, Any], filename: str, size: int) -> str | None:
    """Find the exact uploaded file and byte count in a vendor file-list report.

    Returns:
        Its validated stock G-code path, or None until a matching report arrives.

    Raises:
        RuntimeError: If the printer reports a matching filename at an unsafe path.
    """
    entries: list[tuple[Any, Any, Any]] = []
    modern = change.get("retGcodeFileInfo2")
    if isinstance(modern, list):
        entries.extend(
            (e.get("name"), e.get("file_size"), e.get("path"))
            for e in modern
            if isinstance(e, dict)
        )
    legacy = change.get("retGcodeFileInfo")
    if isinstance(legacy, dict) and isinstance(legacy.get("fileInfo"), str):
        for row in legacy["fileInfo"].split(";"):
            parts = row.split(":")
            if len(parts) >= 3:
                entries.append(
                    (parts[1], parts[2], parts[0].rstrip("/") + "/" + parts[1])
                )
    for name, reported_size, path in entries:
        if name != filename or reported_number(reported_size) != size:
            continue
        if path != GCODE_ROOT + filename:
            raise RuntimeError(
                "The uploaded file was reported outside the stock G-code directory; no start command sent"
            )
        return path
    return None


class CrealityStockAdapter(IntegrationAdapter):
    """Expose stock CR-10 SE telemetry and separately enabled printer controls."""

    id = "creality_stock"
    label = "Creality CR-10 SE (stock)"
    docs_url = "https://github.com/CrealityOfficial/CrealityPrint/tree/v7.3.0/resources/web/deviceMgr"
    experimental = True
    formats = ("gcode",)
    heater_control = True
    slow_action_s = RESUME_TIMEOUT_S
    setup_hint = (
        "CR-10 SE/F003 only. Enable pause and resume separately. Resume waits up "
        "to 90 seconds for PRINTING, including reheating. Power-loss recovery "
        "requires the printer screen. Enable temperature controls separately: "
        "nozzle 0-300 C, bed 0-110 C; 0 switches a heater off. Cancel and the "
        "combined upload-and-start action each require their own permission. "
        "Start accepts sliced .gcode on an idle printer."
    )
    schema = {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "title": "Printer IP",
                "placeholder": "192.168.1.50",
            },
            "port": {"type": "string", "title": "WebSocket port", "default": "9999"},
            "allow_pause": {
                "type": "boolean",
                "title": "Allow pause commands",
                "default": False,
            },
            "allow_resume": {
                "type": "boolean",
                "title": "Allow resume commands",
                "default": False,
            },
            "allow_heat": {
                "type": "boolean",
                "title": "Allow temperature controls",
                "default": False,
            },
            "allow_cancel": {
                "type": "boolean",
                "title": "Allow cancel commands",
                "default": False,
            },
            "allow_print": {
                "type": "boolean",
                "title": "Allow upload and start",
                "default": False,
            },
        },
        "required": ["host"],
    }

    def __init__(self) -> None:
        self._action_locks: dict[str, asyncio.Lock] = {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Read fresh unsolicited state; a quiet socket times out rather than caching it."""
        async with asyncio.timeout(FETCH_TIMEOUT_S):
            async with connect(
                endpoint(config),
                open_timeout=3,
                close_timeout=1,
                ping_interval=None,
                max_size=1048576,
                proxy=None,
            ) as socket:
                return normalise(await snapshot(socket))

    async def heat(
        self, http: HttpFn, config: dict[str, Any], heater: str, target: float
    ) -> None:
        """Set one heater and confirm its reported target, without waiting for heating.

        Raises:
            ValueError: If the heater or temperature is invalid or above a limit.
            RuntimeError: If controls are disabled, the heater is unavailable, or
                the printer does not confirm the requested setpoint.
        """
        target = heater_target(heater, target)
        if config.get("allow_heat") is not True:
            raise RuntimeError(
                "Temperature controls are disabled; enable Allow temperature controls first"
            )
        actual_key, target_key, limit_key = HEATER_FIELDS[heater]
        address = endpoint(config)
        lock = self._action_locks.setdefault(address, asyncio.Lock())
        sent = False
        observed: float | None = None
        try:
            async with asyncio.timeout(HEAT_TIMEOUT_S), lock:
                async with connect(
                    address,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=None,
                    max_size=1048576,
                    proxy=None,
                ) as socket:
                    raw = await snapshot(socket)
                    while actual_key not in raw or target_key not in raw:
                        if normalise(raw).status == DeviceStatus.OFFLINE:
                            raise RuntimeError(
                                "The printer is offline; no heater command sent"
                            )
                        raw.update(await update(socket))
                    current = normalise(raw)
                    if current.status == DeviceStatus.OFFLINE:
                        raise RuntimeError(
                            "The printer is offline; no heater command sent"
                        )
                    if current.status == DeviceStatus.ERROR and target > 0:
                        raise RuntimeError(
                            "The printer reports an error; no heater command sent"
                        )
                    observed = reported_number(raw[target_key])
                    if reported_number(raw[actual_key]) is None or observed is None:
                        raise RuntimeError(
                            f"The printer is not reporting a valid {heater} heater"
                        )
                    reported_limit = reported_number(raw.get(limit_key))
                    if (
                        reported_limit is not None
                        and reported_limit > 0
                        and target > reported_limit
                    ):
                        raise ValueError(
                            f"The {heater} target exceeds the printer's reported limit of {reported_limit:g} C"
                        )
                    if observed == target:
                        return
                    value = int(target) if target.is_integer() else target
                    params = (
                        {"nozzleTempControl": value}
                        if heater == "nozzle"
                        else {"bedTempControl": {"num": 0, "val": value}}
                    )
                    await socket.send(
                        json.dumps(
                            {"method": "set", "params": params}, separators=(",", ":")
                        )
                    )
                    sent = True
                    while True:
                        change = await update(socket)
                        raw.update(change)
                        current = normalise(raw)
                        if current.status == DeviceStatus.OFFLINE:
                            raise RuntimeError(
                                f"The printer went offline; {heater} target was not confirmed"
                            )
                        if target_key not in change:
                            continue
                        observed = reported_number(change[target_key])
                        if observed == target:
                            return
        except TimeoutError as error:
            outcome = (
                "Target was sent but not confirmed"
                if sent
                else "Printer did not provide a heater status; no target sent"
            )
            raise RuntimeError(
                f"{heater}: {outcome}; last reported target={observed}"
            ) from error

    async def send(
        self, http: HttpFn, config: dict[str, Any], action: DeviceAction
    ) -> None:
        """Send an enabled pause, resume or cancel and require its resulting state.

        Raises:
            RuntimeError: If disabled, unsupported, the job is in the wrong state,
                or the printer fails to confirm the resulting state. A socket
                write or a generic acknowledgement is not successful control.
        """
        if action == DeviceAction.RESUME:
            if config.get("allow_resume") is not True:
                raise RuntimeError(
                    "Resume commands are disabled; enable Allow resume commands first"
                )
            await self._resume(config)
            return
        if action == DeviceAction.CANCEL:
            if config.get("allow_cancel") is not True:
                raise RuntimeError(
                    "Cancel commands are disabled; enable Allow cancel commands first"
                )
            await self._cancel(config)
            return
        if action != DeviceAction.PAUSE:
            raise RuntimeError("Unsupported printer action")
        if config.get("allow_pause") is not True:
            raise RuntimeError(
                "Pause commands are disabled; enable Allow pause commands first"
            )
        address = endpoint(config)
        lock = self._action_locks.setdefault(address, asyncio.Lock())
        sent = False
        observed_state: int | None = None
        try:
            async with asyncio.timeout(ACTION_TIMEOUT_S), lock:
                async with connect(
                    address,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=None,
                    max_size=1048576,
                    proxy=None,
                ) as socket:
                    raw = await snapshot(socket)
                    current = normalise(raw)
                    code = state_code(raw.get("state"))
                    if current.status == DeviceStatus.PAUSED:
                        return
                    if raw.get("connect") == 0 or code not in (1, 6):
                        raise RuntimeError(
                            "The printer is not reporting an active or pausing print; no command sent"
                        )
                    if code == 1:
                        await socket.send(PAUSE_MESSAGE)
                        sent = True
                    while True:
                        change = await update(socket)
                        raw.update(change)
                        normalise(raw)
                        if "state" not in change:
                            continue
                        code = state_code(change["state"])
                        observed_state = code
                        if code == 5 and raw.get("connect") != 0:
                            return
        except TimeoutError as error:
            outcome = (
                "Pause was sent but PAUSED was not confirmed"
                if sent
                else "Printer did not confirm a paused state"
            )
            raise RuntimeError(
                f"{outcome}; last reported state={observed_state}"
            ) from error

    async def _resume(self, config: dict[str, Any]) -> None:
        """Resume an ordinary paused job once, waiting through reheating and restoring."""
        address = endpoint(config)
        lock = self._action_locks.setdefault(address, asyncio.Lock())
        sent = False
        observed_state: int | None = None
        try:
            async with asyncio.timeout(RESUME_TIMEOUT_S), lock:
                async with connect(
                    address,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=None,
                    max_size=1048576,
                    proxy=None,
                ) as socket:
                    raw = await snapshot(socket)
                    current = normalise(raw)
                    observed_state = state_code(raw.get("state"))
                    if current.status == DeviceStatus.OFFLINE:
                        raise RuntimeError(
                            "The printer is offline; no resume command sent"
                        )
                    require_normal_resume(raw)
                    if current.status == DeviceStatus.PRINTING:
                        return
                    if observed_state not in (5, 8):
                        raise RuntimeError(
                            "The printer is not paused or restoring; no resume command sent"
                        )
                    if observed_state == 5:
                        await socket.send(RESUME_MESSAGE)
                        sent = True
                    while True:
                        change = await update(socket)
                        raw.update(change)
                        current = normalise(raw)
                        if current.status == DeviceStatus.OFFLINE:
                            raise RuntimeError(
                                "The printer went offline; PRINTING was not confirmed"
                            )
                        require_normal_resume(raw)
                        if "state" not in change:
                            continue
                        observed_state = state_code(change["state"])
                        if observed_state == 1:
                            return
        except TimeoutError as error:
            outcome = (
                "Resume was sent but PRINTING was not confirmed"
                if sent
                else "Printer did not confirm a printing state"
            )
            raise RuntimeError(
                f"{outcome}; last reported state={observed_state}"
            ) from error

    async def _cancel(self, config: dict[str, Any]) -> None:
        """Stop an active job once and require the stock ABORT state, 4."""
        address = endpoint(config)
        lock = self._action_locks.setdefault(address, asyncio.Lock())
        sent = False
        observed_state: int | None = None
        try:
            async with asyncio.timeout(CANCEL_TIMEOUT_S), lock:
                async with connect(
                    address,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=None,
                    max_size=1048576,
                    proxy=None,
                ) as socket:
                    raw = await snapshot(socket)
                    current = normalise(raw)
                    observed_state = state_code(raw.get("state"))
                    if current.status == DeviceStatus.OFFLINE:
                        raise RuntimeError(
                            "The printer is offline; no cancel command sent"
                        )
                    if current.status == DeviceStatus.IDLE:
                        return
                    if observed_state not in (1, 5, 6, 7, 8):
                        raise RuntimeError(
                            "The printer is not reporting an active job; no cancel command sent"
                        )
                    if observed_state != 7:
                        await socket.send(CANCEL_MESSAGE)
                        sent = True
                    while True:
                        change = await update(socket)
                        raw.update(change)
                        current = normalise(raw)
                        if current.status == DeviceStatus.OFFLINE:
                            raise RuntimeError(
                                "The printer went offline; cancellation was not confirmed"
                            )
                        if "state" not in change:
                            continue
                        observed_state = state_code(change["state"])
                        if observed_state == 4:
                            return
        except TimeoutError as error:
            outcome = (
                "Cancel was sent but ABORT was not confirmed"
                if sent
                else "Printer did not confirm cancellation"
            )
            raise RuntimeError(
                f"{outcome}; last reported state={observed_state}"
            ) from error

    async def print_file(
        self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes
    ) -> None:
        """Upload sliced G-code and start it through PrintGuard's standard action.

        Args:
            http: Platform HTTP function, with the engine's redirect refusal.
            config: Stock CR-10 SE connection and explicit control permissions.
            filename: A plain .gcode filename, as supplied by the print library.
            data: The sliced file bytes, uploaded without rewriting the G-code.

        Raises:
            ValueError: If the filename or file data cannot be uploaded.
            RuntimeError: If disabled, not idle, upload not verified, or the
                new job is not confirmed. A failed start is never retried.
        """
        if config.get("allow_print") is not True:
            raise RuntimeError(
                "Upload and start are disabled; enable Allow upload and start first"
            )
        remote_name = upload_name(filename, data)
        address = endpoint(config)
        host = urlsplit(address).hostname
        base_url = f"http://[{host}]" if ":" in host else f"http://{host}"
        lock = self._action_locks.setdefault(address, asyncio.Lock())
        stage = "checking idle state; no upload or start sent"
        try:
            async with (
                asyncio.timeout(
                    UPLOAD_TIMEOUT_S + 2 * FILE_TIMEOUT_S + START_TIMEOUT_S + 15
                ),
                lock,
            ):
                async with asyncio.timeout(FETCH_TIMEOUT_S):
                    async with connect(
                        address,
                        open_timeout=3,
                        close_timeout=1,
                        ping_interval=None,
                        max_size=1048576,
                        proxy=None,
                    ) as socket:
                        require_idle(await snapshot(socket))
                status, info = await http(
                    "GET",
                    base_url + "/info",
                    headers={"Connection": "close"},
                    timeout=FETCH_TIMEOUT_S,
                )
                if (
                    status != 200
                    or not isinstance(info, dict)
                    or info.get("model") != EXPECTED_MODEL
                ):
                    raise RuntimeError(
                        "The upload service did not identify the CR-10 SE (F003); no file sent"
                    )
                headers, body = upload_form(base_url, remote_name, data)
                stage = "upload attempted; file may be stored, no start sent"
                status, uploaded = await http(
                    "POST",
                    base_url + "/upload/" + quote(remote_name, safe=""),
                    headers=headers,
                    data=body,
                    timeout=UPLOAD_TIMEOUT_S,
                )
                if status != 200:
                    raise RuntimeError(
                        f"Upload returned HTTP {status}; no start command sent"
                    )
                if not isinstance(uploaded, dict) or uploaded.get("code") != 200:
                    raise RuntimeError(
                        "The printer did not confirm upload success (code 200); no start command sent"
                    )
                stage = "verifying uploaded file; no start sent"
                async with connect(
                    address,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=None,
                    max_size=1048576,
                    proxy=None,
                ) as socket:
                    async with asyncio.timeout(FILE_TIMEOUT_S):
                        raw = await snapshot(socket)
                        require_idle(raw)
                        await socket.send(FILES_MESSAGE)
                        while True:
                            change = await update(socket)
                            raw.update(change)
                            require_idle(raw)
                            path = listed_file(change, remote_name, len(data))
                            if path is not None:
                                break
                    stage = "start sent; PRINTING with the uploaded filename not confirmed, check printer before retrying"
                    message = {
                        "method": "set",
                        "params": {
                            "opGcodeFile": "printprt:" + path,
                            "enableSelfTest": 0,
                        },
                    }
                    async with asyncio.timeout(START_TIMEOUT_S):
                        await socket.send(json.dumps(message, separators=(",", ":")))
                        confirmation: dict[str, Any] = {}
                        while True:
                            change = await update(socket)
                            raw.update(change)
                            current = normalise(raw)
                            if current.status in (
                                DeviceStatus.OFFLINE,
                                DeviceStatus.ERROR,
                            ):
                                raise RuntimeError(
                                    "Printer went offline or reported an error; start was not confirmed"
                                )
                            confirmation.update(change)
                            job = confirmation.get("printFileName")
                            if state_code(confirmation.get("state")) == 1 and job in (
                                path,
                                remote_name,
                            ):
                                return
        except TimeoutError as error:
            raise RuntimeError(f"Upload/start timed out: {stage}") from error
        except TransportError as error:
            raise RuntimeError(
                f"Upload/start HTTP {type(error).__name__}: {stage}; do not automatically retry"
            ) from error
