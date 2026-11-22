import { useState } from "react";
import { useStore } from "../store";
import { useSubmit } from "../submit";
import type { MqttConfig } from "../types";
import { addressMoved, retypeReason } from "./SchemaForm";
import { SecretInput } from "./SecretInput";
import { Toggle } from "./Toggle";

export function HomeAssistantTab() {
  const { engine, isPending } = useStore();
  const [mqtt, setMqtt] = useState<MqttConfig>(engine?.settings.mqtt ?? {});
  const saveBroker = useSubmit(() => setMqtt(engine?.settings.mqtt ?? {}));
  const setMqttField = (key: keyof MqttConfig, value: MqttConfig[keyof MqttConfig]) => setMqtt({ ...mqtt, [key]: value });
  const savedPassword = engine?.secrets_set?.mqtt.includes("password") ?? false;
  const brokerProblem =
    mqtt.enabled && !mqtt.host?.trim()
      ? "Enter the broker host."
      : retypeReason(mqtt, engine?.settings.mqtt ?? {}, savedPassword ? { password: "Password" } : {});
  return (
    <div className="space-y-3">
      <Toggle label="Publish to an MQTT broker" on={!!mqtt.enabled} onChange={(on) => setMqttField("enabled", on)} />
      {mqtt.enabled && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              className="field flex-1"
              aria-label="Broker host"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              placeholder="Broker host (e.g. 192.168.1.10)"
              value={mqtt.host ?? ""}
              onChange={(e) => setMqttField("host", e.target.value)}
            />
            <input
              className="field shrink-0"
              style={{ width: "5rem" }}
              type="number"
              inputMode="numeric"
              min={1}
              max={65535}
              step={1}
              aria-label="Broker port"
              placeholder={mqtt.tls ? "8883" : "1883"}
              value={mqtt.port ?? ""}
              onChange={(e) => setMqttField("port", e.target.value ? Number(e.target.value) : undefined)}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              className="field flex-1 basis-32"
              aria-label="Username"
              autoCapitalize="none"
              autoCorrect="off"
              placeholder="Username (optional)"
              value={mqtt.username ?? ""}
              onChange={(e) => setMqttField("username", e.target.value)}
            />
            <SecretInput
              name="password"
              aria-label="Password"
              placeholder="Password (optional)"
              saved={savedPassword}
              retype={addressMoved(mqtt, engine?.settings.mqtt ?? {})}
              value={mqtt.password}
              onChange={(password) => setMqttField("password", password)}
            />
          </div>
          <div className="flex gap-2">
            <input
              className="field flex-1"
              aria-label="Base topic"
              autoCapitalize="none"
              autoCorrect="off"
              placeholder="Base topic (printguard)"
              value={mqtt.base_topic ?? ""}
              onChange={(e) => setMqttField("base_topic", e.target.value)}
            />
            <input
              className="field flex-1"
              aria-label="Discovery prefix"
              autoCapitalize="none"
              autoCorrect="off"
              placeholder="Discovery prefix (homeassistant)"
              value={mqtt.discovery_prefix ?? ""}
              onChange={(e) => setMqttField("discovery_prefix", e.target.value)}
            />
          </div>
          <Toggle label="Use TLS" on={!!mqtt.tls} onChange={(on) => setMqttField("tls", on)} />
          <span className="block text-sm text-text-2">
            Each monitor shows up as a Home Assistant device via MQTT discovery, with its defect sensor, score, state,
            latest snapshot, enable switch and printer pause, resume and cancel controls. Keep in mind that anyone with
            access to your broker can control PrintGuard.
          </span>
        </div>
      )}
      <button
        className="btn btn-primary"
        disabled={isPending("settings.update") || brokerProblem !== null}
        onClick={() => saveBroker.submit({ cmd: "settings.update", patch: { mqtt } })}
      >
        {isPending("settings.update") ? "Saving…" : "Save broker settings"}
      </button>
      {brokerProblem && <span className="block text-sm text-text-2">{brokerProblem}</span>}
      {saveBroker.error && (
        <span role="alert" className="chip chip-message chip-bad">
          {saveBroker.error}
        </span>
      )}
      <span className="block text-sm text-text-2">
        Broker settings open a live connection, so changes apply once you click Save.
      </span>
    </div>
  );
}
