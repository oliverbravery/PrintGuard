"""Bambu Lab integration over the printer's local MQTT API.

Bambu Lab printers expose no local HTTP control surface: state and control
travel over MQTT/TLS on port 8883, authenticated with the LAN access code.
That needs a raw TLS socket, which the browser sandbox forbids, so this
adapter runs in hub mode only (browser_ok is False).

The user must enable LAN Only Mode and then Developer Mode on the printer
(Settings > Network) — Developer Mode is what opens the MQTT channel on
current firmware. The access code is shown on that screen; the serial
number is under Settings > Device.

Protocol reference: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
TLS and command shapes mirror the bambulabs_api client:
https://github.com/acse-ci223/bambulabs_api/blob/main/bambulabs_api/mqtt_client.py
"""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter

_PORT = 8883
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

    def _client(self, config: dict[str, Any]):
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.connect_timeout = _CONNECT_TIMEOUT_S
        client.username_pw_set(_USERNAME, str(config.get("access_code", "")))
        client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
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
