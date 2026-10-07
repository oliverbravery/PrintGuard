"""MQTT bridge protocol shapes: Home Assistant discovery payloads, the
per-monitor state blob and inbound command routing - the pure functions the
bridge's aiomqtt session is a thin wrapper around."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
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
        self.passwords: list[str | None] = []
        self.published: list[tuple[str, Any, bool]] = []

    def client(self, **options: Any) -> "FakeBroker":
        self.identifiers.append(options["identifier"])
        self.passwords.append(options["password"])
        return self

    async def __aenter__(self) -> "FakeBroker":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False, timeout: float | None = None) -> None:
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


class CommandedBroker(FakeBroker):
    """A broker that delivers Home Assistant's button presses, then goes quiet."""

    def __init__(self, topics: list[str]) -> None:
        super().__init__()
        self._waiting = [SimpleNamespace(topic=topic, payload=b"on") for topic in topics]

    async def __anext__(self) -> Any:
        if self._waiting:
            return self._waiting.pop(0)
        await asyncio.Event().wait()


async def test_commands_behind_a_slow_printer_run_side_by_side_and_in_order_for_one_monitor(monkeypatch) -> None:
    """The loop awaited each command in turn, so a burst of presses ran late and one after another."""
    engine = Engine(FakePlatform())
    await engine.start()
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    for name in ("Left", "Middle", "Right"):
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": name, "camera_id": next(iter(engine.cameras.items))}})
    left, middle, right = list(engine.monitors)
    topics = [f"printguard/monitor/{monitor}/enabled/set" for monitor in (left, middle, right, left)]
    broker = CommandedBroker(topics)
    monkeypatch.setattr(mqtt.aiomqtt, "Client", broker.client)
    steps: list[tuple[str, str]] = []

    async def slow_request(command: dict[str, Any]) -> list[dict[str, Any]]:
        steps.append(("start", command["id"]))
        await asyncio.sleep(0.3)
        steps.append(("end", command["id"]))
        return []

    monkeypatch.setattr(engine, "request", slow_request)
    bridge = mqtt.MqttBridge(engine, lambda: {"enabled": True, "host": "broker"})
    bridge.start()
    try:
        began = asyncio.get_running_loop().time()
        await _until(lambda: len([step for step in steps if step[0] == "end"]) == 4)
        took = asyncio.get_running_loop().time() - began
    finally:
        await bridge.stop()
        await engine.stop()

    assert took < 0.9, f"four commands took {took:.2f} s, one after the other"
    assert [step for step in steps if step[1] == left] == [("start", left), ("end", left)] * 2, "a monitor's presses overlapped"
    assert steps[:3] == [("start", left), ("start", middle), ("start", right)]


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


async def test_a_removed_monitor_leaves_nothing_retained_even_when_the_bridge_was_off(monkeypatch) -> None:
    config = {"enabled": True, "host": "broker"}
    broker, engine, bridge = await _bridged(monkeypatch, config)

    def retained(monitor_id: str) -> set[str]:
        kept: dict[str, Any] = {}
        for topic, payload, retain in broker.published:
            if retain and monitor_id in topic:
                kept[topic] = payload
        return {topic for topic, payload in kept.items() if payload != ""}

    try:
        await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
        for name in ("Left", "Right"):
            await engine.handle({"cmd": "monitor.add", "monitor": {"name": name, "camera_id": next(iter(engine.cameras.items))}})
        left, right = list(engine.monitors)
        await _until(lambda: len(retained(left)) == 2 and len(retained(right)) == 2)

        await engine.handle({"cmd": "monitor.remove", "id": right})
        await _until(lambda: not retained(right))

        config["enabled"] = False
        engine.emit({"event": "state"})
        await _until(lambda: broker.published[-1] == OFFLINE)
        await engine.handle({"cmd": "monitor.remove", "id": left})
        config["enabled"] = True
        await _until(lambda: broker.published.count(ONLINE) == 2)
        await _until(lambda: not retained(left))
    finally:
        await bridge.stop()
        await engine.stop()


async def test_a_bridge_survives_settings_it_cannot_use(monkeypatch) -> None:
    config: dict[str, Any] = {"enabled": True, "host": "broker", "port": "abc"}
    broker, engine, bridge = await _bridged(monkeypatch, config)
    warnings: list[dict[str, Any]] = []
    engine.add_sink(lambda event: warnings.append(event) if event.get("event") == "warning" else None)
    try:
        await _until(lambda: warnings)
        assert "Home Assistant MQTT unavailable" in warnings[0]["message"]
        config["port"] = 1883
        await _until(lambda: ONLINE in broker.published)
    finally:
        await bridge.stop()
        await engine.stop()


async def test_a_dead_broker_warns_once_and_again_when_it_is_back(monkeypatch) -> None:
    """A warning per attempt pushes every alert out of the engine's recent events in minutes."""
    broker, engine, bridge = await _bridged(monkeypatch, {"enabled": True, "host": "broker"})
    attempts: list[bool] = []
    reachable = False

    async def connect() -> FakeBroker:
        attempts.append(reachable)
        if not reachable:
            raise mqtt.aiomqtt.MqttError("[Errno 111] Connection refused")
        return broker

    monkeypatch.setattr(FakeBroker, "__aenter__", lambda self: connect())
    try:
        await _until(lambda: len(attempts) > 5)
        reachable = True
        await _until(lambda: ONLINE in broker.published)
        warnings = [event for event in engine.recent_events() if event["event"] == "warning"]
    finally:
        await bridge.stop()
        await engine.stop()

    assert [(warning["message"], warning["recovered"]) for warning in warnings] == [
        ("Home Assistant MQTT unavailable: [Errno 111] Connection refused", False),
        ("Home Assistant MQTT reconnected", True),
    ]


async def test_a_broker_that_drops_the_session_is_reported_with_its_reason(monkeypatch) -> None:
    """The command loop's task group wrapped it, so the warning read "unhandled errors in a TaskGroup (1 sub-exception)"."""

    class Dropping(FakeBroker):
        async def __anext__(self) -> Any:
            raise mqtt.aiomqtt.MqttError("Disconnected during message iteration")

    broker = Dropping()
    monkeypatch.setattr(mqtt.aiomqtt, "Client", broker.client)
    monkeypatch.setattr(mqtt, "RECONNECT_DELAY_S", 0.01)
    engine = Engine(FakePlatform())
    await engine.start()
    bridge = mqtt.MqttBridge(engine, lambda: {"enabled": True, "host": "broker"})
    bridge.start()
    try:
        await _until(lambda: any(event["event"] == "warning" for event in engine.recent_events()))
        warnings = [event["message"] for event in engine.recent_events() if event["event"] == "warning"]
    finally:
        await bridge.stop()
        await engine.stop()

    assert warnings[0] == "Home Assistant MQTT unavailable: Disconnected during message iteration"


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
        async def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False, timeout: float | None = None) -> None:
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


async def test_a_command_that_times_out_says_what_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Sends(FakeBroker):
        async def __anext__(self) -> Any:
            if getattr(self, "sent", False):
                await asyncio.Event().wait()
            self.sent = True
            await asyncio.sleep(0.2)
            return SimpleNamespace(topic=f"printguard/monitor/{monitor_id}/enabled/set", payload=b"ON")

    broker = Sends()
    monkeypatch.setattr(mqtt.aiomqtt, "Client", broker.client)
    engine = Engine(FakePlatform())
    await engine.start()
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": next(iter(engine.cameras.items))}})
    monitor_id = next(iter(engine.monitors))

    async def timed_out(command: dict[str, Any], **_: Any) -> list[dict[str, Any]]:
        raise TimeoutError

    monkeypatch.setattr(engine, "request", timed_out)
    bridge = mqtt.MqttBridge(engine, lambda: {"enabled": True, "host": "broker"})
    bridge.start()
    try:
        await _until(lambda: any(e["event"] == "error" for e in engine.recent_events()))
        assert [e["message"] for e in engine.recent_events() if e["event"] == "error"] == ["Home Assistant command failed: TimeoutError"]
    finally:
        await bridge.stop()
        await engine.stop()


def _warnings(engine: Engine) -> list[tuple[str, bool]]:
    return [(event["message"], event["recovered"]) for event in engine.recent_events() if event["event"] == "warning"]


async def test_a_broker_that_takes_the_connection_but_refuses_the_subscription_warns_once(monkeypatch) -> None:
    """Each attempt connected, cleared the outage and said reconnected, then failed and said unavailable again."""
    broker, engine, bridge = await _bridged(monkeypatch, {"enabled": True, "host": "broker"})

    async def refuse(*_: Any, **__: Any) -> None:
        raise mqtt.aiomqtt.MqttError("Could not subscribe")

    attempts = 0

    def connect(**options: Any) -> FakeBroker:
        nonlocal attempts
        attempts += 1
        return broker.client(**options)

    monkeypatch.setattr(mqtt.aiomqtt, "Client", connect)
    monkeypatch.setattr(broker, "subscribe", refuse)
    try:
        await _until(lambda: attempts > 5)
        warnings = _warnings(engine)
    finally:
        await bridge.stop()
        await engine.stop()

    assert warnings == [("Home Assistant MQTT unavailable: Could not subscribe", False)]


@pytest.mark.parametrize("setting", ["base_topic", "discovery_prefix"])
@pytest.mark.parametrize("topic", ["print+guard", "a/#"])
async def test_a_topic_with_a_wildcard_is_a_bad_setting_reported_once_and_never_connected(monkeypatch, setting: str, topic: str) -> None:
    config: dict[str, Any] = {"enabled": True, "host": "broker", setting: topic}
    broker, engine, bridge = await _bridged(monkeypatch, config)
    try:
        await _until(lambda: _warnings(engine))
        await asyncio.sleep(0.1)
        warnings = _warnings(engine)
        assert warnings == [(f"Home Assistant MQTT unavailable: MQTT {setting} cannot contain + or #", False)]
        assert not broker.identifiers, "the bridge connected with a topic the broker client refuses to publish to"

        config[setting] = "printguard"
        await _until(lambda: ONLINE in broker.published)
    finally:
        await bridge.stop()
        await engine.stop()


async def test_the_bridge_signs_in_with_the_password_the_snapshot_leaves_out(monkeypatch) -> None:
    """The bridge hears the same redacted state as every transport, so the password has to come from the settings."""
    broker, engine, bridge = await _bridged(monkeypatch, {})
    bridge._get_config = lambda: engine.settings["mqtt"]
    try:
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {"enabled": True, "host": "broker", "password": "mq-s3cret-pass"}}})
        await _until(lambda: ONLINE in broker.published)
        shown = engine.state_event()
        await engine.handle({"cmd": "settings.update", "patch": {"mqtt": {**shown["settings"]["mqtt"], "username": "pg"}}})
        await _until(lambda: broker.published.count(ONLINE) == 2)
    finally:
        await bridge.stop()
        await engine.stop()

    assert "password" not in shown["settings"]["mqtt"] and shown["secrets_set"]["mqtt"] == ["password"]
    assert broker.passwords == ["mq-s3cret-pass", "mq-s3cret-pass"]
