"""MQTT bridge protocol shapes: Home Assistant discovery payloads, the
per-monitor state blob and inbound command routing — the pure functions the
bridge's aiomqtt session is a thin wrapper around."""

from __future__ import annotations

from typing import Any

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


def test_monitor_state_phase_and_score() -> None:
    assert mqtt.monitor_state(_monitor(), None, 0.5)["state"] == "watching"
    assert mqtt.monitor_state(_monitor(), None, 0.5)["score"] == 50.0
    assert mqtt.monitor_state(_monitor(enabled=False), None, None)["state"] == "disabled"
    assert mqtt.monitor_state(_monitor(watching=False), None, None)["state"] == "idle"
    triggered = mqtt.monitor_state(_monitor(alert={"score": 0.9, "action": "pause", "ts": 1.0}), None, 0.9)
    assert triggered["state"] == "triggered"
    assert triggered["defect"] == "on"


def test_monitor_state_includes_linked_printer_fields() -> None:
    payload = mqtt.monitor_state(_monitor(printer_id="prn1"), _printer(), 0.1)
    assert payload["printer_status"] == "printing"
    assert payload["progress"] == 42.5
    assert payload["job"] == "boat.gcode"
    assert "printer_status" not in mqtt.monitor_state(_monitor(), None, 0.1)


def test_state_changed_damps_score_drift_but_not_transitions() -> None:
    watching = mqtt.monitor_state(_monitor(), None, 0.40)
    assert mqtt.state_changed(None, watching)
    assert not mqtt.state_changed(watching, watching)
    assert not mqtt.state_changed(watching, mqtt.monitor_state(_monitor(), None, 0.43))
    assert mqtt.state_changed(watching, mqtt.monitor_state(_monitor(), None, 0.46))
    triggered = mqtt.monitor_state(_monitor(alert={"score": 0.41, "action": "none", "ts": 1.0}), None, 0.41)
    assert mqtt.state_changed(watching, triggered)
    printing = mqtt.monitor_state(_monitor(printer_id="prn1"), _printer(), 0.1)
    paused = mqtt.monitor_state(_monitor(printer_id="prn1"), _printer(device_state={"status": "paused", "progress": 42.6, "job": "boat.gcode"}), 0.1)
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
