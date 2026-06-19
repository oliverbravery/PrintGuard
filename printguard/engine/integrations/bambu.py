"""Bambu Lab integration over the printer's local MQTT API.

Bambu Lab printers expose no local HTTP control surface: state and control
travel over MQTT/TLS on port 8883, authenticated with the LAN access code.
That needs a raw TLS socket, which the browser sandbox forbids, so this
adapter runs in hub mode only (browser_ok is False).

The user must enable LAN Only Mode and then Developer Mode on the printer
(Settings > Network) — Developer Mode is what opens the MQTT channel on
current firmware. The access code is shown on that screen; the serial
number is under Settings > Device.

Printer-side setup (LAN Only Mode, Developer Mode): https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
Protocol reference: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
TLS and command shapes mirror the bambulabs_api client:
https://github.com/acse-ci223/bambulabs_api/blob/main/bambulabs_api/mqtt_client.py
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter

_PORT = 8883
_RTSP_PORT = 322
_CAMERA_PORT = 6000
_USERNAME = "bblp"
_CONNECT_TIMEOUT_S = 5.0
_REPLY_TIMEOUT_S = 5.0
_DEADLINE_S = 12.0
_KEEPALIVE_S = 30

_STATUS_MAP = {
    "running": DeviceStatus.PRINTING,
    "prepare": DeviceStatus.PRINTING,
    "pause": DeviceStatus.PAUSED,
    "idle": DeviceStatus.IDLE,
    "finish": DeviceStatus.IDLE,
    "failed": DeviceStatus.ERROR,
}

_COMMANDS = {DeviceAction.PAUSE: "pause", DeviceAction.RESUME: "resume", DeviceAction.CANCEL: "stop"}

_PUSHALL = {"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}}


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
    browser_ok = False
    experimental = True
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

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Requests a full status push and normalises gcode_state.

        The HTTP function is unused: Bambu speaks MQTT, not HTTP.
        """
        loop = asyncio.get_running_loop()
        report = await asyncio.wait_for(loop.run_in_executor(None, self._pull_report, config), _DEADLINE_S)
        if not report:
            return DeviceState(DeviceStatus.OFFLINE)
        matched = _STATUS_MAP.get(str(report.get("gcode_state", "")).lower(), DeviceStatus.UNKNOWN)
        progress = float(report.get("mc_percent") or 0.0)
        job = report.get("subtask_name") or report.get("gcode_file") or None
        return DeviceState(matched, progress, job)

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Publishes a pause/resume/stop command to the request topic."""
        payload = {"print": {"sequence_id": "0", "command": _COMMANDS[action], "param": ""}}
        loop = asyncio.get_running_loop()
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

    def _rtsps_fingerprint(self, host: str) -> str | None:
        import hashlib
        import socket
        import ssl

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection((host, _RTSP_PORT), timeout=_CONNECT_TIMEOUT_S) as raw:
                with context.wrap_socket(raw, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
        except OSError:
            return None
        return hashlib.sha256(der).hexdigest().upper() if der else None

    def _port_open(self, host: str, port: int) -> bool:
        import socket

        try:
            with socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S):
                return True
        except OSError:
            return False

    def _client(self, config: dict[str, Any]):
        import ssl

        import paho.mqtt.client as mqtt

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.connect_timeout = _CONNECT_TIMEOUT_S
        client.username_pw_set(_USERNAME, str(config.get("access_code", "")))
        client.tls_set_context(context)
        client.connect(str(config["host"]), _PORT, keepalive=_KEEPALIVE_S)
        return client

    def _pull_report(self, config: dict[str, Any]) -> dict[str, Any] | None:
        serial = str(config["serial"])
        report: dict[str, Any] = {}
        received = threading.Event()

        def on_connect(client, *_):
            client.subscribe(f"device/{serial}/report")
            client.publish(f"device/{serial}/request", json.dumps(_PUSHALL))

        def on_message(_client, _userdata, message):
            try:
                payload = json.loads(message.payload).get("print") or {}
            except ValueError:
                return
            if "gcode_state" in payload:
                report.update(payload)
                received.set()

        client = self._client(config)
        client.on_connect = on_connect
        client.on_message = on_message
        client.loop_start()
        received.wait(_REPLY_TIMEOUT_S)
        client.loop_stop()
        client.disconnect()
        return report or None

    def _publish(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        client = self._client(config)
        client.loop_start()
        info = client.publish(f"device/{config['serial']}/request", json.dumps(payload), qos=1)
        info.wait_for_publish(_REPLY_TIMEOUT_S)
        client.loop_stop()
        client.disconnect()
