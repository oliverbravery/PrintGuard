"""MQTT bridge protocol shapes: Home Assistant discovery payloads, the
per-monitor state blob and inbound command routing - the pure functions the
bridge's aiomqtt session is a thin wrapper around."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.server import mqtt


def _monitor(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "abc12345",
        "name": "Front printer",
        "camera_id": "cam1",
        "printer_id": "",
        "enabled": True,
        "alert": None,
        "watching": True,
    }
    return {**base, **overrides}


HEATED = {"status": "printing", "progress": 42.5, "job": "boat.gcode", "nozzle": {"actual": 209.94, "target": 210.0}, "bed": None}


def _printer(**overrides: Any) -> dict[str, Any]:
    base = {"id": "prn1", "name": "Ender", "provider": "octoprint", "device_state": {"status": "printing", "progress": 42.5, "job": "boat.gcode"}}
    return {**base, **overrides}


def test_bridge_enabled_needs_a_host_and_the_switch() -> None:
    assert not mqtt.bridge_enabled({})
    assert not mqtt.bridge_enabled({"enabled": True})
    assert not mqtt.bridge_enabled({"enabled": False, "host": "broker"})
    assert mqtt.bridge_enabled({"enabled": True, "host": "broker"})


def test_topic_helpers_default_and_strip() -> None:
    assert mqtt.base_topic({}) == "printguard"
    assert mqtt.base_topic({"base_topic": "/pg/"}) == "pg"
    assert mqtt.discovery_prefix({}) == "homeassistant"
    assert mqtt.status_topic("pg") == "pg/status"
    assert mqtt.state_topic("pg", "m1") == "pg/monitor/m1/state"
    assert mqtt.device_config_topic("homeassistant", "m1") == "homeassistant/device/printguard_m1/config"


def test_discovery_config_is_device_based_and_well_formed() -> None:
    config = mqtt.discovery_config(_monitor(), None, "2.2.0", "printguard")
    assert set(config) >= {"device", "origin", "components", "availability_topic", "state_topic"}
    assert config["device"]["identifiers"] == ["printguard_abc12345"]
    assert config["device"]["name"] == "Front printer"
    assert config["origin"]["name"] == "PrintGuard"
    assert config["availability_topic"] == "printguard/status"
    assert config["state_topic"] == "printguard/monitor/abc12345/state"
    for component in config["components"].values():
        assert component["p"]
        assert component["unique_id"].startswith("printguard_abc12345_")
    assert config["components"]["defect"]["device_class"] == "problem"
    assert config["components"]["enabled"]["command_topic"] == "printguard/monitor/abc12345/enabled/set"


def test_discovery_config_omits_printer_entities_without_a_printer() -> None:
    monitor_only = mqtt.discovery_config(_monitor(), None, "2.2.0", "printguard")
    assert "pause" not in monitor_only["components"]
    assert "progress" not in monitor_only["components"]
    with_printer = mqtt.discovery_config(_monitor(printer_id="prn1"), _printer(), "2.2.0", "printguard")
    assert {"pause", "resume", "cancel", "progress", "printer_status"} <= set(with_printer["components"])
    action_topic = "printguard/monitor/abc12345/printer_action/set"
    assert with_printer["components"]["pause"]["command_topic"] == action_topic
    assert with_printer["components"]["pause"]["payload_press"] == "pause"
    assert with_printer["components"]["cancel"]["payload_press"] == "cancel"


def test_heaters_appear_once_the_printer_reports_them() -> None:
    without = mqtt.discovery_config(_monitor(printer_id="prn1"), _printer(), "2.4.2", "printguard")
    assert {"nozzle", "bed"}.isdisjoint(without["components"])
    heated = mqtt.discovery_config(_monitor(printer_id="prn1"), _printer(device_state=HEATED), "2.4.2", "printguard")
    assert "bed" not in heated["components"], "a heater the printer does not report gets no sensor"
    nozzle = heated["components"]["nozzle"]
    assert nozzle["device_class"] == "temperature" and nozzle["unit_of_measurement"] == "°C"
    assert nozzle["value_template"] == "{{ value_json.nozzle_temp }}"
    payload = mqtt.monitor_state(_monitor(printer_id="prn1", result={"score": 0.1, "ts": 1.0}), _printer(device_state=HEATED))
    assert payload["nozzle_temp"] == 209.9 and "bed_temp" not in payload
    warmer = mqtt.monitor_state(
        _monitor(printer_id="prn1", result={"score": 0.1, "ts": 1.0}),
        _printer(device_state={**HEATED, "nozzle": {"actual": 213.0, "target": 210.0}}),
    )
    assert not mqtt.state_changed(payload, warmer), "a few degrees of drift is within the deadband"


def test_monitor_state_phase_and_score() -> None:
    assert mqtt.monitor_state(_monitor(result={"score": 0.5, "ts": 1.0}), None)["state"] == "watching"
    assert mqtt.monitor_state(_monitor(result={"score": 0.5, "ts": 1.0}), None)["score"] == 50.0
    assert mqtt.monitor_state(_monitor(result={"score": 0.42, "ts": 1.0}), None)["score"] == 42.0
    assert mqtt.monitor_state(_monitor(enabled=False), None)["state"] == "disabled"
    assert mqtt.monitor_state(_monitor(watching=False), None)["state"] == "idle"
    triggered = mqtt.monitor_state(
        _monitor(alert={"score": 0.9, "action": "pause", "ts": 1.0}, result={"score": 0.9, "ts": 1.0}),
        None,
    )
    assert triggered["state"] == "triggered"
    assert triggered["defect"] == "on"


def test_monitor_state_includes_linked_printer_fields() -> None:
    payload = mqtt.monitor_state(_monitor(printer_id="prn1", result={"score": 0.1, "ts": 1.0}), _printer())
    assert payload["printer_status"] == "printing"
    assert payload["progress"] == 42.5
    assert payload["job"] == "boat.gcode"
    assert "printer_status" not in mqtt.monitor_state(_monitor(result={"score": 0.1, "ts": 1.0}), None)


def test_state_changed_damps_score_drift_but_not_transitions() -> None:
    watching = mqtt.monitor_state(_monitor(result={"score": 0.40, "ts": 1.0}), None)
    assert mqtt.state_changed(None, watching)
    assert not mqtt.state_changed(watching, watching)
    assert not mqtt.state_changed(watching, mqtt.monitor_state(_monitor(result={"score": 0.43, "ts": 2.0}), None))
    assert mqtt.state_changed(watching, mqtt.monitor_state(_monitor(result={"score": 0.46, "ts": 2.0}), None))
    triggered = mqtt.monitor_state(
        _monitor(alert={"score": 0.41, "action": "none", "ts": 1.0}, result={"score": 0.41, "ts": 1.0}),
        None,
    )
    assert mqtt.state_changed(watching, triggered)
    printing = mqtt.monitor_state(_monitor(printer_id="prn1", result={"score": 0.1, "ts": 1.0}), _printer())
    paused = mqtt.monitor_state(
        _monitor(printer_id="prn1", result={"score": 0.1, "ts": 1.0}),
        _printer(device_state={"status": "paused", "progress": 42.6, "job": "boat.gcode"}),
    )
    assert mqtt.state_changed(printing, paused)


def test_route_command_maps_enabled_switch() -> None:
    monitors = [_monitor()]
    on = mqtt.route_command("printguard/monitor/abc12345/enabled/set", "ON", monitors)
    assert on == {"cmd": "monitor.update", "id": "abc12345", "patch": {"enabled": True}}
    off = mqtt.route_command("printguard/monitor/abc12345/enabled/set", "off", monitors)
    assert off["patch"] == {"enabled": False}


def test_route_command_maps_printer_actions_only_with_a_printer() -> None:
    with_printer = [_monitor(printer_id="prn1")]
    command = mqtt.route_command("printguard/monitor/abc12345/printer_action/set", "pause", with_printer)
    assert command == {"cmd": "printer.action", "id": "prn1", "action": "pause"}
    assert mqtt.route_command("printguard/monitor/abc12345/printer_action/set", "pause", [_monitor()]) is None
    assert mqtt.route_command("printguard/monitor/abc12345/printer_action/set", "explode", with_printer) is None


def test_route_command_rejects_unknown_topics_and_monitors() -> None:
    monitors = [_monitor()]
    assert mqtt.route_command("printguard/monitor/abc12345/enabled/set", "ON", []) is None
    assert mqtt.route_command("printguard/monitor/nope/enabled/set", "ON", monitors) is None
    assert mqtt.route_command("printguard/status", "online", monitors) is None
    assert mqtt.route_command("printguard/monitor/abc12345/enabled/get", "ON", monitors) is None


def test_signature_changes_with_connection_settings() -> None:
    base = {"enabled": True, "host": "broker", "port": 1883}
    assert mqtt._signature(base) == mqtt._signature(dict(base))
    assert mqtt._signature(base) != mqtt._signature({**base, "host": "other"})
    assert mqtt._signature(base) != mqtt._signature({**base, "tls": True})


def test_route_command_ignores_a_payload_that_is_neither_on_nor_off() -> None:
    topic = "printguard/monitor/abc12345/enabled/set"
    for payload in ("", "toggle", "garbage"):
        assert mqtt.route_command(topic, payload, [_monitor()]) is None, f"{payload!r} must not disable the monitor"
    assert mqtt.route_command(topic, "0", [_monitor()])["patch"] == {"enabled": False}


class FakeBroker:
    """Stands in for aiomqtt.Client, keeping what a session was opened with and published."""

    def __init__(self) -> None:
        self.identifiers: list[str] = []
        self.published: list[tuple[str, Any, bool]] = []

    def client(self, **options: Any) -> "FakeBroker":
        self.identifiers.append(options["identifier"])
        return self

    async def __aenter__(self) -> "FakeBroker":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> None:
        self.published.append((topic, payload, retain))

    async def subscribe(self, *_: Any, **__: Any) -> None:
        return None

    @property
    def messages(self) -> "FakeBroker":
        return self

    def __aiter__(self) -> "FakeBroker":
        return self

    async def __anext__(self) -> Any:
        await asyncio.Event().wait()


ONLINE = ("printguard/status", "online", True)
OFFLINE = ("printguard/status", "offline", True)


async def _bridged(monkeypatch, config: dict[str, Any]):
    broker = FakeBroker()
    monkeypatch.setattr(mqtt.aiomqtt, "Client", broker.client)
    monkeypatch.setattr(mqtt, "RECONNECT_DELAY_S", 0.01)
    engine = Engine(FakePlatform())
    await engine.start()
    bridge = mqtt.MqttBridge(engine, lambda: config)
    bridge.start()
    return broker, engine, bridge


async def _until(condition) -> None:
    async with asyncio.timeout(2):
        while not condition():
            await asyncio.sleep(0.01)


async def test_a_bridge_that_stops_tells_home_assistant_the_hub_is_offline(monkeypatch) -> None:
    """A clean disconnect discards the last will, so nothing else would say so."""
    config = {"enabled": True, "host": "broker"}
    broker, engine, bridge = await _bridged(monkeypatch, config)
    try:
        await _until(lambda: ONLINE in broker.published)
        config["enabled"] = False
        engine.emit({"event": "state"})
        await _until(lambda: broker.published[-1] == OFFLINE)

        config["enabled"] = True
        await _until(lambda: broker.published.count(ONLINE) == 2)
        await bridge.stop()
        assert broker.published[-1] == OFFLINE
    finally:
        await bridge.stop()
        await engine.stop()


async def test_a_bridge_survives_settings_it_cannot_use(monkeypatch) -> None:
    config: dict[str, Any] = {"enabled": True, "host": "broker", "port": "abc"}
    broker, engine, bridge = await _bridged(monkeypatch, config)
    warnings: list[dict[str, Any]] = []
    engine.add_sink(lambda event: warnings.append(event) if event.get("event") == "warning" else None)
    try:
        await _until(lambda: len(warnings) > 1)
        assert "Home Assistant MQTT unavailable" in warnings[0]["message"]
        config["port"] = 1883
        await _until(lambda: ONLINE in broker.published)
    finally:
        await bridge.stop()
        await engine.stop()


async def test_settings_refuse_an_mqtt_port_that_is_not_one() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        for port in ("abc", 70000, -1, 1883.5):
            with pytest.raises(RuntimeError, match="MQTT port"):
                await engine.request({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True, "host": "broker", "port": port}}})
        await engine.request({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True, "host": "broker", "port": 8883}}})
        await engine.request({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True, "host": "broker"}}})
    finally:
        await engine.stop()


async def test_two_hubs_on_one_broker_do_not_share_a_client_id(monkeypatch) -> None:
    """The process id is 1 in every container, and a broker hands a session to the newest client using an id."""
    broker, engine, first = await _bridged(monkeypatch, {"enabled": True, "host": "broker"})
    second = mqtt.MqttBridge(engine, lambda: {"enabled": True, "host": "broker"})
    second.start()
    try:
        await _until(lambda: len(broker.identifiers) == 2)
        assert len(set(broker.identifiers)) == 2
    finally:
        await first.stop()
        await second.stop()
        await engine.stop()



async def test_a_bridge_stops_when_the_broker_has_already_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stop that waited on telling a dead broker the hub is offline would hold the whole shutdown up."""

    class Gone(FakeBroker):
        async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> None:
            if payload == "offline":
                raise mqtt.aiomqtt.MqttError("broker gone")
            await super().publish(topic, payload, qos, retain)

    broker = Gone()
    monkeypatch.setattr(mqtt.aiomqtt, "Client", broker.client)
    engine = Engine(FakePlatform())
    await engine.start()
    bridge = mqtt.MqttBridge(engine, lambda: {"enabled": True, "host": "broker"})
    bridge.start()
    await _until(lambda: ONLINE in broker.published)
    try:
        await asyncio.wait_for(bridge.stop(), 2)
    finally:
        await engine.stop()
