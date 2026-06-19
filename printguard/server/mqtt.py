"""Home Assistant MQTT bridge (hub mode only).

A thin layer over the engine's event sink and ``request()``
surface that owns no monitoring logic of its own. It reconciles one Home
Assistant device per monitor through MQTT *device-based* discovery, publishes
each monitor's state and failure snapshot, and routes inbound Home Assistant
commands (the Enabled switch and the printer Pause/Resume/Cancel buttons) back
through ``engine.request()`` — so PrintGuard appears as a first-class,
controllable device in Home Assistant without the engine knowing MQTT exists.

Connection settings live in engine settings under ``mqtt`` and are edited from
the dashboard like notifier channels; the bridge reconnects when they change.
A raw MQTT socket is forbidden in the browser sandbox, so this is hub-only.

The protocol shapes are pure functions tested in ``tests/test_mqtt.py``; this
module wraps them in an ``aiomqtt`` session that reconnects on failure and on a
settings change. Control is gated only by access to the broker, which is the
standard Home Assistant MQTT trust model.

Discovery format: https://www.home-assistant.io/integrations/mqtt/#device-discovery
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
from typing import TYPE_CHECKING, Any, Callable

import aiomqtt

if TYPE_CHECKING:
    from ..engine.engine import Engine

RECONNECT_DELAY_S = 5.0
KEEPALIVE_S = 30
QUEUE_MAX = 512
MANUFACTURER = "PrintGuard"
MODEL = "Print monitor"
SUPPORT_URL = "https://github.com/oliverbravery/PrintGuard"


def bridge_enabled(config: dict[str, Any]) -> bool:
    """Whether the bridge has somewhere to connect and is switched on."""
    return bool(config.get("enabled")) and bool(str(config.get("host", "")).strip())


def base_topic(config: dict[str, Any]) -> str:
    """Root topic every PrintGuard topic hangs off, defaulting to ``printguard``."""
    return str(config.get("base_topic") or "printguard").strip("/")


def discovery_prefix(config: dict[str, Any]) -> str:
    """Home Assistant discovery prefix, defaulting to ``homeassistant``."""
    return str(config.get("discovery_prefix") or "homeassistant").strip("/")


def status_topic(base: str) -> str:
    """Retained availability topic backing the last-will message."""
    return f"{base}/status"


def state_topic(base: str, monitor_id: str) -> str:
    """Topic carrying the JSON blob a monitor's entities template from."""
    return f"{base}/monitor/{monitor_id}/state"


def snapshot_topic(base: str, monitor_id: str) -> str:
    """Topic carrying a monitor's latest defect snapshot as a JPEG."""
    return f"{base}/monitor/{monitor_id}/snapshot"


def enabled_command_topic(base: str, monitor_id: str) -> str:
    """Topic Home Assistant publishes the Enabled switch state to."""
    return f"{base}/monitor/{monitor_id}/enabled/set"


def action_command_topic(base: str, monitor_id: str) -> str:
    """Topic Home Assistant publishes a printer action to (pause/resume/cancel)."""
    return f"{base}/monitor/{monitor_id}/printer_action/set"


def device_config_topic(prefix: str, monitor_id: str) -> str:
    """Retained device-discovery config topic for a monitor's Home Assistant device."""
    return f"{prefix}/device/printguard_{monitor_id}/config"


def monitor_state(monitor: dict[str, Any], printer: dict[str, Any] | None, score: float | None) -> dict[str, Any]:
    """Builds the state blob a monitor's Home Assistant entities read.

    Defect and watching follow the monitor's own ``alert`` and ``watching``
    fields from the engine snapshot, which the watchdog already maintains and
    clears, so the bridge derives no monitoring state of its own.
    """
    if not monitor.get("enabled"):
        phase = "disabled"
    elif monitor.get("alert"):
        phase = "triggered"
    elif monitor.get("watching"):
        phase = "watching"
    else:
        phase = "idle"
    payload: dict[str, Any] = {
        "enabled": "on" if monitor.get("enabled") else "off",
        "watching": "on" if monitor.get("watching") else "off",
        "defect": "on" if monitor.get("alert") else "off",
        "state": phase,
        "score": round((score or 0.0) * 100, 1),
    }
    if printer:
        device = printer.get("device_state") or {}
        payload["printer_status"] = device.get("status", "unknown")
        payload["progress"] = round(float(device.get("progress") or 0.0), 1)
        payload["job"] = device.get("job")
    return payload


def discovery_config(monitor: dict[str, Any], printer: dict[str, Any] | None, version: str, base: str) -> dict[str, Any]:
    """Builds a monitor's Home Assistant device-discovery payload.

    One device per monitor, its components sharing a single state topic and
    templating their own field out of it. Printer controls and sensors appear
    only when the monitor is bound to a printer.
    """
    monitor_id = monitor["id"]

    def unique(key: str) -> str:
        return f"printguard_{monitor_id}_{key}"

    components: dict[str, dict[str, Any]] = {
        "defect": {
            "p": "binary_sensor",
            "unique_id": unique("defect"),
            "name": "Defect",
            "device_class": "problem",
            "value_template": "{{ value_json.defect }}",
            "payload_on": "on",
            "payload_off": "off",
        },
        "score": {
            "p": "sensor",
            "unique_id": unique("score"),
            "name": "Defect score",
            "unit_of_measurement": "%",
            "state_class": "measurement",
            "value_template": "{{ value_json.score }}",
            "icon": "mdi:image-search",
        },
        "phase": {
            "p": "sensor",
            "unique_id": unique("phase"),
            "name": "State",
            "value_template": "{{ value_json.state }}",
            "icon": "mdi:cctv",
        },
        "enabled": {
            "p": "switch",
            "unique_id": unique("enabled"),
            "name": "Enabled",
            "value_template": "{{ value_json.enabled }}",
            "payload_on": "on",
            "payload_off": "off",
            "command_topic": enabled_command_topic(base, monitor_id),
            "icon": "mdi:motion-sensor",
        },
        "snapshot": {
            "p": "camera",
            "unique_id": unique("snapshot"),
            "name": "Snapshot",
            "topic": snapshot_topic(base, monitor_id),
        },
    }
    if printer:
        action_topic = action_command_topic(base, monitor_id)
        components |= {
            "printer_status": {
                "p": "sensor",
                "unique_id": unique("printer_status"),
                "name": "Printer",
                "value_template": "{{ value_json.printer_status }}",
                "icon": "mdi:printer-3d",
            },
            "progress": {
                "p": "sensor",
                "unique_id": unique("progress"),
                "name": "Progress",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "value_template": "{{ value_json.progress }}",
                "icon": "mdi:progress-clock",
            },
            "pause": {"p": "button", "unique_id": unique("pause"), "name": "Pause", "command_topic": action_topic, "payload_press": "pause", "icon": "mdi:pause"},
            "resume": {"p": "button", "unique_id": unique("resume"), "name": "Resume", "command_topic": action_topic, "payload_press": "resume", "icon": "mdi:play"},
            "cancel": {"p": "button", "unique_id": unique("cancel"), "name": "Cancel", "command_topic": action_topic, "payload_press": "cancel", "icon": "mdi:stop"},
        }
    return {
        "device": {"identifiers": [f"printguard_{monitor_id}"], "name": monitor.get("name") or "Monitor", "manufacturer": MANUFACTURER, "model": MODEL, "sw_version": version},
        "origin": {"name": "PrintGuard", "sw_version": version, "support_url": SUPPORT_URL},
        "availability_topic": status_topic(base),
        "payload_available": "online",
        "payload_not_available": "offline",
        "state_topic": state_topic(base, monitor_id),
        "components": components,
    }


def route_command(topic: str, payload: str, monitors: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Maps an inbound Home Assistant command topic to an engine command.

    Returns None for any topic, payload or monitor that does not resolve to a
    valid command, so an unexpected message is ignored rather than acted on.
    """
    parts = topic.split("/")
    if len(parts) < 5 or parts[-1] != "set" or parts[-4] != "monitor":
        return None
    monitor_id, field = parts[-3], parts[-2]
    monitor = next((m for m in monitors if m.get("id") == monitor_id), None)
    if monitor is None:
        return None
    value = payload.strip().lower()
    if field == "enabled":
        return {"cmd": "monitor.update", "id": monitor_id, "patch": {"enabled": value in ("on", "true", "1")}}
    if field == "printer_action" and value in ("pause", "resume", "cancel") and monitor.get("printer_id"):
        return {"cmd": "printer.action", "id": monitor["printer_id"], "action": value}
    return None


def _signature(config: dict[str, Any]) -> tuple:
    """Connection-affecting settings; a change tears the session down to reconnect."""
    return (
        bool(config.get("enabled")),
        str(config.get("host", "")).strip(),
        int(config.get("port") or 0),
        str(config.get("username") or ""),
        str(config.get("password") or ""),
        bool(config.get("tls")),
        base_topic(config),
        discovery_prefix(config),
    )


class _Reconnect(Exception):
    """Raised to drop the session cleanly when the broker settings change."""


class MqttBridge:
    """Publishes monitor state to MQTT and routes Home Assistant commands back.

    The bridge subscribes to engine events as a transport sink, draining them
    through a queue so the synchronous sink never blocks the engine, and keeps
    one ``aiomqtt`` session alive while the bridge is enabled, reconnecting on
    failure and on a settings change.
    """

    def __init__(self, engine: "Engine", get_config: Callable[[], dict[str, Any]]) -> None:
        self._engine = engine
        self._get_config = get_config
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._scores: dict[str, float] = {}
        self._published: dict[str, str] = {}
        self._devices: set[str] = set()
        self._state: dict[str, Any] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Launches the connection loop; it idles until the bridge is configured."""
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        """Cancels the connection loop and any in-flight session."""
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def _sink(self, event: dict[str, Any]) -> None:
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(event)

    async def _run(self) -> None:
        while True:
            config = self._get_config()
            if not bridge_enabled(config):
                await asyncio.sleep(RECONNECT_DELAY_S)
                continue
            try:
                await self._session(config)
            except _Reconnect:
                continue
            except aiomqtt.MqttError as exc:
                self._engine.emit({"event": "warning", "message": f"Home Assistant MQTT unavailable: {exc}", "recovered": False})
                await asyncio.sleep(RECONNECT_DELAY_S)

    async def _session(self, config: dict[str, Any]) -> None:
        base = base_topic(config)
        prefix = discovery_prefix(config)
        signature = _signature(config)
        tls_context = ssl.create_default_context() if config.get("tls") else None
        async with aiomqtt.Client(
            hostname=str(config["host"]).strip(),
            port=int(config.get("port") or (8883 if config.get("tls") else 1883)),
            username=str(config.get("username") or "") or None,
            password=str(config.get("password") or "") or None,
            identifier=f"printguard-{os.getpid()}",
            tls_context=tls_context,
            will=aiomqtt.Will(status_topic(base), "offline", qos=1, retain=True),
            keepalive=KEEPALIVE_S,
        ) as client:
            self._published.clear()
            self._devices.clear()
            self._state = {}
            await client.publish(status_topic(base), "online", qos=1, retain=True)
            await client.subscribe(f"{base}/monitor/+/+/set", qos=1)
            self._engine.add_sink(self._sink)
            tasks = [
                asyncio.ensure_future(self._publish_loop(client, base, prefix, signature)),
                asyncio.ensure_future(self._command_loop(client, base)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                for task in done:
                    task.result()
            finally:
                self._engine.remove_sink(self._sink)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _publish_loop(self, client: aiomqtt.Client, base: str, prefix: str, signature: tuple) -> None:
        while True:
            event = await self._queue.get()
            if _signature(self._get_config()) != signature:
                raise _Reconnect
            await self._handle(client, event, base, prefix)

    async def _command_loop(self, client: aiomqtt.Client, base: str) -> None:
        async for message in client.messages:
            command = route_command(str(message.topic), bytes(message.payload).decode("utf-8", "ignore"), self._state.get("monitors", []))
            if command is None:
                continue
            try:
                await self._engine.request(command)
            except Exception as exc:
                self._engine.emit({"event": "error", "message": f"Home Assistant command failed: {exc}"})

    async def _handle(self, client: aiomqtt.Client, event: dict[str, Any], base: str, prefix: str) -> None:
        kind = event.get("event")
        if kind == "state":
            await self._reconcile(client, event, base, prefix)
        elif kind == "result":
            self._scores[event["monitor_id"]] = event.get("score", 0.0)
            await self._publish_state(client, event["monitor_id"], base)
        elif kind == "alert":
            await self._publish_snapshot(client, event["monitor_id"], base)

    async def _reconcile(self, client: aiomqtt.Client, state: dict[str, Any], base: str, prefix: str) -> None:
        self._state = state
        version = state.get("version", "")
        printers = {p["id"]: p for p in state.get("printers", [])}
        desired = set()
        for monitor in state.get("monitors", []):
            monitor_id = monitor["id"]
            desired.add(monitor_id)
            printer = printers.get(monitor.get("printer_id") or "")
            await self._publish(client, device_config_topic(prefix, monitor_id), json.dumps(discovery_config(monitor, printer, version, base)))
            await self._publish_state(client, monitor_id, base)
        for monitor_id in self._devices - desired:
            await client.publish(device_config_topic(prefix, monitor_id), "", qos=1, retain=True)
            self._published.pop(device_config_topic(prefix, monitor_id), None)
            self._published.pop(state_topic(base, monitor_id), None)
        self._devices = desired

    async def _publish_state(self, client: aiomqtt.Client, monitor_id: str, base: str) -> None:
        monitor = next((m for m in self._state.get("monitors", []) if m["id"] == monitor_id), None)
        if monitor is None:
            return
        printer = next((p for p in self._state.get("printers", []) if p["id"] == monitor.get("printer_id")), None)
        payload = monitor_state(monitor, printer, self._scores.get(monitor_id))
        await self._publish(client, state_topic(base, monitor_id), json.dumps(payload))

    async def _publish_snapshot(self, client: aiomqtt.Client, monitor_id: str, base: str) -> None:
        monitor = next((m for m in self._state.get("monitors", []) if m["id"] == monitor_id), None)
        if monitor is None or not monitor.get("camera_id"):
            return
        jpeg = await self._engine.snapshot(monitor["camera_id"])
        if jpeg:
            await client.publish(snapshot_topic(base, monitor_id), jpeg, qos=1, retain=True)

    async def _publish(self, client: aiomqtt.Client, topic: str, payload: str) -> None:
        """Publishes a retained topic only when its payload has changed."""
        if self._published.get(topic) == payload:
            return
        self._published[topic] = payload
        await client.publish(topic, payload, qos=1, retain=True)
