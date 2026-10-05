"""Bambu Lab integration over the printer's local MQTT API.

Bambu Lab printers expose no local HTTP control surface: state and control
travel over MQTT/TLS on port 8883, authenticated with the LAN access code.

The user must enable LAN Only Mode and then Developer Mode on the printer
(Settings > Network) - Developer Mode is what opens the MQTT channel on
current firmware. The access code is shown on that screen; the serial
number is under Settings > Device.

A sliced 3mf reaches the printer over FTPS on port 990, implicit TLS with the
same credentials, and the print is then started over MQTT with the
``project_file`` command, which is what Bambu Studio does when it sends a
plate. The printer's FTP server insists the data connection reuses the control
connection's TLS session, which ftplib does not do on its own.

One subscribed connection is held per printer. The X1 series reports its whole
state every time and the P1 and A1 series only what changed, so reports are
merged over the full one ``pushall`` returns, which is asked for once per
connection because the P1P lags when asked often. The printer answers a command
on the report topic with the ``sequence_id`` it was sent and a ``result``.

Printer-side setup (LAN Only Mode, Developer Mode): https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
Protocol reference: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
TLS and command shapes mirror the bambulabs_api client:
https://github.com/acse-ci223/bambulabs_api/blob/main/bambulabs_api/mqtt_client.py
Connection handling, the silence limit and the H2 file URL mirror ha-bambulab:
https://github.com/greghesp/ha-bambulab/tree/main/custom_components/bambu_lab
"""

from __future__ import annotations

import asyncio
import ftplib
import hashlib
import io
import itertools
import json
import queue
import random
import socket
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from ..gcode import plate_gcode
from .base import DeviceAction, DeviceState, DeviceStatus, Heater, HttpFn, IntegrationAdapter

_PORT = 8883
_FTP_PORT = 990
_RTSP_PORT = 322
_CAMERA_PORT = 6000
_USERNAME = "bblp"
_CONNECT_TIMEOUT_S = 5.0
_REPLY_TIMEOUT_S = 5.0
_DEADLINE_S = 12.0
_UPLOAD_DEADLINE_S = 300.0
_KEEPALIVE_S = 30
_SILENCE_LIMIT_S = 60.0

_STATUS_MAP = {
    "running": DeviceStatus.PRINTING,
    "prepare": DeviceStatus.PRINTING,
    "pause": DeviceStatus.PAUSED,
    "idle": DeviceStatus.IDLE,
    "finish": DeviceStatus.IDLE,
    "failed": DeviceStatus.ERROR,
}

_COMMANDS = {DeviceAction.PAUSE: "pause", DeviceAction.RESUME: "resume", DeviceAction.CANCEL: "stop"}
_HEATER_GCODE = {"nozzle": "M104", "bed": "M140"}

_PUSHALL = {"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}}
_GET_VERSION = {"info": {"sequence_id": "0", "command": "get_version"}}
_FTP_URL_PRODUCTS = {"Bambu Lab H2C", "Bambu Lab H2D", "Bambu Lab H2S"}
_PROJECT_FILE = {
    "sequence_id": "0",
    "command": "project_file",
    "bed_type": "auto",
    "timelapse": False,
    "bed_leveling": True,
    "flow_cali": False,
    "vibration_cali": False,
    "layer_inspect": False,
    "use_ams": False,
    "ams_mapping": [0],
    "profile_id": "0",
    "project_id": "0",
    "subtask_id": "0",
    "task_id": "0",
}


def _tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class _Session:
    """One subscribed MQTT connection to a printer, holding its merged report."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Connects, subscribes and asks for the printer's version and full report.

        Raises:
            OSError: If the printer cannot be reached.
            RuntimeError: If it refuses the connection or never answers it.
        """
        serial = str(config["serial"])
        self._report_topic = f"device/{serial}/report"
        self._request_topic = f"device/{serial}/request"
        self._report: dict[str, Any] = {}
        self._full = threading.Event()
        self._answered = threading.Event()
        self._refusal = ""
        self._product = ""
        self._versioned = threading.Event()
        self._heard_at = time.monotonic()
        self._echoes: dict[tuple[str, str], queue.SimpleQueue[dict[str, Any]]] = {}
        self._sequence = itertools.count(random.randrange(100_000, 1_000_000))
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        self._client.connect_timeout = _CONNECT_TIMEOUT_S
        self._client.username_pw_set(_USERNAME, str(config.get("access_code", "")))
        self._client.tls_set_context(_tls_context())
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.connect(str(config["host"]), _PORT, keepalive=_KEEPALIVE_S)
        self._client.loop_start()
        if not self._answered.wait(_CONNECT_TIMEOUT_S) or self._refusal:
            self.close()
            raise RuntimeError(f"Bambu printer refused the connection: {self._refusal or 'no answer'}")

    def lost(self) -> bool:
        """Whether the connection dropped or the printer has gone silent on it."""
        return not self._client.is_connected() or time.monotonic() - self._heard_at > _SILENCE_LIMIT_S

    def report(self) -> dict[str, Any] | None:
        """The merged report, or None while this connection has no full one."""
        return dict(self._report) if self._full.wait(_REPLY_TIMEOUT_S) else None

    def product(self) -> str:
        """The model name the printer gives in its version reply, empty if it gives none."""
        self._versioned.wait(_REPLY_TIMEOUT_S)
        return self._product

    def command(self, payload: dict[str, Any]) -> None:
        """Publishes a command under its own sequence number and checks it was taken.

        The broker's acknowledgement is required. The printer's own answer is
        waited for and a failed one raises, while a printer that sends none is
        taken at the broker's word.

        Args:
            payload: The request, one command under its type key.

        Raises:
            RuntimeError: If the publish is not acknowledged, or the printer
                answers that the command failed.
        """
        ((kind, body),) = payload.items()
        body = {**body, "sequence_id": str(next(self._sequence))}
        key = (body["command"], body["sequence_id"])
        echoes = self._echoes[key] = queue.SimpleQueue()
        try:
            sent = self._client.publish(self._request_topic, json.dumps({kind: body}), qos=1)
            sent.wait_for_publish(_REPLY_TIMEOUT_S)
            if not sent.is_published():
                raise RuntimeError(f"Bambu printer did not acknowledge {body['command']}")
            try:
                echo = echoes.get(timeout=_REPLY_TIMEOUT_S)
            except queue.Empty:
                return
        finally:
            del self._echoes[key]
        result = str(echo.get("result", ""))
        if result.lower().startswith("fail"):
            raise RuntimeError(f"Bambu printer refused {body['command']}: {echo.get('reason') or result}")

    def close(self) -> None:
        """Disconnects and stops the network thread."""
        self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        if reason_code.is_failure:
            self._refusal = str(reason_code)
        else:
            self._report.clear()
            self._full.clear()
            self._heard_at = time.monotonic()
            client.subscribe(self._report_topic)
            client.publish(self._request_topic, json.dumps(_GET_VERSION))
            client.publish(self._request_topic, json.dumps(_PUSHALL))
        self._answered.set()

    def _on_disconnect(self, *_: Any) -> None:
        self._full.clear()

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload)
        except ValueError:
            return
        self._heard_at = time.monotonic()
        for body in payload.values():
            if not isinstance(body, dict):
                continue
            command = body.get("command")
            if command == "push_status":
                self._report.update(body)
                if "gcode_state" in self._report:
                    self._full.set()
            elif command == "get_version":
                self._product = next((m["product_name"] for m in body.get("module") or [] if m.get("product_name")), "")
                self._versioned.set()
            elif echoes := self._echoes.get((command, body.get("sequence_id"))):
                echoes.put(body)


class BambuAdapter(IntegrationAdapter):
    """Talks to a Bambu Lab printer's local MQTT API in LAN Only Mode."""

    id = "bambu"
    label = "Bambu Lab"
    docs_url = "https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md"
    setup_url = "https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode"
    setup_hint = (
        "On the printer, enable LAN Only Mode then Developer Mode (Settings > Network) to open the MQTT "
        "channel. The access code is shown there; the serial number is under Settings > Device."
    )
    experimental = False
    formats = ("3mf",)
    heater_control = True
    schema = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "title": "Printer IP", "placeholder": "192.168.1.70"},
            "serial": {"type": "string", "title": "Serial number", "placeholder": "Settings > Device"},
            "access_code": {
                "type": "string",
                "title": "Access code",
                "secret": True,
                "placeholder": "8-character access code",
            },
        },
        "required": ["host", "serial", "access_code"],
    }

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, str], _Session] = {}
        self._session_locks: dict[tuple[str, str, str], threading.Lock] = {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Normalises gcode_state from the printer's latest merged report.

        The HTTP function is unused: Bambu speaks MQTT, not HTTP. The report's
        remaining time is in minutes. A printer with no full report on a live
        connection is offline.
        """
        loop = asyncio.get_running_loop()
        report = await asyncio.wait_for(loop.run_in_executor(None, self._pull_report, config), _DEADLINE_S)
        if not report:
            return DeviceState(DeviceStatus.OFFLINE)
        matched = _STATUS_MAP.get(str(report.get("gcode_state", "")).lower(), DeviceStatus.UNKNOWN)
        progress = float(report.get("mc_percent") or 0.0)
        job = report.get("subtask_name") or report.get("gcode_file") or None
        remaining = report.get("mc_remaining_time")
        return DeviceState(
            matched,
            progress,
            job,
            remaining_s=int(remaining) * 60 if remaining is not None else None,
            nozzle=Heater.reported(report.get("nozzle_temper"), report.get("nozzle_target_temper")),
            bed=Heater.reported(report.get("bed_temper"), report.get("bed_target_temper")),
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Publishes a pause/resume/stop command to the request topic.

        Raises:
            RuntimeError: If the printer does not acknowledge the command or
                answers that it failed, as it does with Developer Mode off.
        """
        payload = {"print": {"sequence_id": "0", "command": _COMMANDS[action], "param": ""}}
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(loop.run_in_executor(None, self._publish, config, payload), _DEADLINE_S)

    async def heat(self, http: HttpFn, config: dict[str, Any], heater: str, target: float) -> None:
        """Sets a heater target with the M104 or M140 line Bambu Studio sends over gcode_line."""
        payload = {"print": {"sequence_id": "0", "command": "gcode_line", "param": f"{_HEATER_GCODE[heater]} S{target:g}\n"}}
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(loop.run_in_executor(None, self._publish, config, payload), _DEADLINE_S)

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Uploads a sliced 3mf to the SD card over FTPS and prints its first plate.

        The print carries the settings sliced into the file. Bed levelling is
        left on and the flow and vibration calibrations off, and the filament
        comes from the external spool or the first AMS slot, since a file says
        nothing about the AMS it was sliced against. The H2 series is handed
        the file as an FTP URL and every other model as a path on the SD card.
        """
        plate, _ = plate_gcode(data)
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(loop.run_in_executor(None, self._upload, config, filename, data), _UPLOAD_DEADLINE_S)
        product = await asyncio.wait_for(loop.run_in_executor(None, self._product, config), _DEADLINE_S)
        payload = {
            "print": {
                **_PROJECT_FILE,
                "param": f"Metadata/plate_{plate}.gcode",
                "url": f"ftp:///{filename}" if product in _FTP_URL_PRODUCTS else f"file:///sdcard/{filename}",
                "subtask_name": filename.rsplit(".", 1)[0],
            }
        }
        await asyncio.wait_for(loop.run_in_executor(None, self._publish, config, payload), _DEADLINE_S)

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Exposes the chamber camera over whichever transport the model serves.

        X1- and H2-series printers serve RTSPS on port 322; its self-signed
        certificate's fingerprint travels with the source so MediaMTX validates
        the stream. The A1 and P1 series have no RTSP and instead stream JPEG
        frames over a proprietary protocol on port 6000, which the hub reads
        directly. A probe picks the transport the printer actually offers.
        """
        host = str(config.get("host", ""))
        access_code = str(config.get("access_code", ""))
        if not host:
            return []
        loop = asyncio.get_running_loop()
        fingerprint = await loop.run_in_executor(None, self._rtsps_fingerprint, host)
        if fingerprint:
            url = f"rtsps://{_USERNAME}:{access_code}@{host}:{_RTSP_PORT}/streaming/live/1"
            return [{"key": "chamber", "name": "Chamber camera", "source": {"kind": "url", "url": url, "fingerprint": fingerprint}}]
        if await loop.run_in_executor(None, self._port_open, host, _CAMERA_PORT):
            return [{"key": "chamber", "name": "Chamber camera", "source": {"kind": "bambu", "host": host, "access_code": access_code}}]
        return []

    async def close(self, config: dict[str, Any] | None = None) -> None:
        """Disconnects one printer's MQTT session, or every session."""
        await asyncio.to_thread(self._drop, config)

    def _rtsps_fingerprint(self, host: str) -> str | None:
        context = _tls_context()
        try:
            with socket.create_connection((host, _RTSP_PORT), timeout=_CONNECT_TIMEOUT_S) as raw:
                with context.wrap_socket(raw, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
        except OSError:
            return None
        return hashlib.sha256(der).hexdigest().upper() if der else None

    def _port_open(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S):
                return True
        except OSError:
            return False

    def _upload(self, config: dict[str, Any], filename: str, data: bytes) -> None:
        context = _tls_context()

        class ImplicitFtps(ftplib.FTP_TLS):
            """FTPS with TLS from the first byte, the data channel on the control channel's session.

            The control socket is wrapped the moment it is assigned, before ftplib
            reads the welcome banner, which is what implicit TLS needs.
            """

            _sock: Any = None

            @property
            def sock(self) -> Any:
                return self._sock

            @sock.setter
            def sock(self, value: Any) -> None:
                if value is not None and not isinstance(value, ssl.SSLSocket):
                    value = context.wrap_socket(value, server_hostname=self.host)
                self._sock = value

            def ntransfercmd(self, cmd: str, rest: Any = None) -> tuple[Any, Any]:
                conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
                return context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session), size

        ftps = ImplicitFtps(context=context, timeout=_CONNECT_TIMEOUT_S)
        ftps.connect(str(config["host"]), _FTP_PORT)
        try:
            ftps.login(_USERNAME, str(config.get("access_code", "")))
            ftps.prot_p()
            ftps.storbinary(f"STOR {filename}", io.BytesIO(data))
        finally:
            ftps.close()

    def _session_key(self, config: dict[str, Any]) -> tuple[str, str, str]:
        return str(config["host"]), str(config["serial"]), str(config.get("access_code", ""))

    def _session(self, config: dict[str, Any]) -> _Session:
        key = self._session_key(config)
        with self._session_locks.setdefault(key, threading.Lock()):
            session = self._sessions.get(key)
            if session is None:
                session = self._sessions[key] = _Session(config)
            return session

    def _drop(self, config: dict[str, Any] | None) -> None:
        keys = [self._session_key(config)] if config is not None else list(self._sessions)
        for key in keys:
            with self._session_locks.setdefault(key, threading.Lock()):
                session = self._sessions.pop(key, None)
                if session is not None:
                    session.close()

    def _pull_report(self, config: dict[str, Any]) -> dict[str, Any] | None:
        session = self._session(config)
        if session.lost():
            self._drop(config)
            session = self._session(config)
        return session.report()

    def _product(self, config: dict[str, Any]) -> str:
        return self._session(config).product()

    def _publish(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        if self._session(config).lost():
            self._drop(config)
        try:
            self._session(config).command(payload)
        except Exception:
            self._drop(config)
            raise
