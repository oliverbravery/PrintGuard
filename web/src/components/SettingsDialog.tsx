import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { ApiToken, MqttConfig } from "../types";
import { Dialog } from "./Dialog";
import { SchemaForm } from "./SchemaForm";
import { Toggle } from "./Toggle";

export function SettingsDialog() {
  const { engine, send, openDialog, leaveMode, isPending, notifyTest, testingNotifier, testNotifier, createdToken, clearCreatedToken } = useStore();
  const [notifiers, setNotifiers] = useState(engine?.settings.notifiers ?? {});
  const [updateCheck, setUpdateCheck] = useState(engine?.settings.update_check ?? true);
  const [mqtt, setMqtt] = useState<MqttConfig>(engine?.settings.mqtt ?? {});
  const setMqttField = (key: keyof MqttConfig, value: MqttConfig[keyof MqttConfig]) => setMqtt({ ...mqtt, [key]: value });
  const [tokenName, setTokenName] = useState("");
  const [tokenScope, setTokenScope] = useState<ApiToken["scope"]>("read");
  const saving = isPending("settings.update");
  const sent = useRef(false);
  const close = () => openDialog(null);
  const tokens = engine?.tokens ?? [];

  useEffect(() => {
    if (sent.current && !saving) close();
  }, [saving]);

  const channels = (engine?.notifiers ?? []).filter((n) => engine?.mode === "hub" || n.browser_ok);

  return (
    <Dialog title="Settings" onClose={close}>
      <div className="space-y-5">
        <div className="space-y-4">
          <span className="label block">Notification channels</span>
          {channels.map((meta) => {
            const enabled = meta.id in notifiers;
            return (
              <div key={meta.id} className="space-y-3">
                <Toggle
                  label={meta.label}
                  on={enabled}
                  onChange={(on) => {
                    const next = { ...notifiers };
                    if (on) next[meta.id] = next[meta.id] ?? {};
                    else delete next[meta.id];
                    setNotifiers(next);
                  }}
                />
                {enabled && (
                  <>
                    <SchemaForm
                      meta={meta}
                      value={notifiers[meta.id]}
                      onChange={(config) => setNotifiers({ ...notifiers, [meta.id]: config })}
                    />
                    <div className="flex items-center gap-3">
                      <button
                        className="btn"
                        disabled={testingNotifier !== null}
                        onClick={() => testNotifier(meta.id, notifiers[meta.id])}
                      >
                        {testingNotifier === meta.id ? "Sending…" : "Send test alert"}
                      </button>
                      {notifyTest?.provider === meta.id && (
                        <span className={`chip ${notifyTest.ok ? "chip-ok" : "chip-bad"}`}>
                          {notifyTest.ok ? "sent" : notifyTest.error || "failed"}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
          <span className="text-[0.7rem] text-text-2 block">
            Defect alerts (with snapshots) go to every enabled channel for printers with notifications on.
          </span>
        </div>
        {engine?.mode === "hub" && (
          <div className="space-y-3">
            <span className="label block">Home Assistant (MQTT)</span>
            <Toggle label="Publish to an MQTT broker" on={!!mqtt.enabled} onChange={(on) => setMqttField("enabled", on)} />
            {mqtt.enabled && (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input
                    className="field flex-1"
                    placeholder="Broker host (e.g. 192.168.1.10)"
                    value={mqtt.host ?? ""}
                    onChange={(e) => setMqttField("host", e.target.value)}
                  />
                  <input
                    className="field shrink-0"
                    style={{ width: "5rem" }}
                    type="number"
                    placeholder={mqtt.tls ? "8883" : "1883"}
                    value={mqtt.port ?? ""}
                    onChange={(e) => setMqttField("port", e.target.value ? Number(e.target.value) : undefined)}
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    className="field flex-1"
                    placeholder="Username (optional)"
                    value={mqtt.username ?? ""}
                    onChange={(e) => setMqttField("username", e.target.value)}
                  />
                  <input
                    className="field flex-1"
                    type="password"
                    placeholder="Password (optional)"
                    value={mqtt.password ?? ""}
                    onChange={(e) => setMqttField("password", e.target.value)}
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    className="field flex-1"
                    placeholder="Base topic (printguard)"
                    value={mqtt.base_topic ?? ""}
                    onChange={(e) => setMqttField("base_topic", e.target.value)}
                  />
                  <input
                    className="field flex-1"
                    placeholder="Discovery prefix (homeassistant)"
                    value={mqtt.discovery_prefix ?? ""}
                    onChange={(e) => setMqttField("discovery_prefix", e.target.value)}
                  />
                </div>
                <Toggle label="Use TLS" on={!!mqtt.tls} onChange={(on) => setMqttField("tls", on)} />
                <span className="text-[0.7rem] text-text-2 block">
                  Each monitor becomes a Home Assistant device — defect, score, state and snapshot, with an enable switch and
                  printer pause/resume/cancel — via MQTT discovery. Anyone with broker access can control PrintGuard.
                </span>
              </div>
            )}
          </div>
        )}
        {engine?.mode === "hub" && (
          <div className="space-y-3">
            <span className="label block">Software updates</span>
            <Toggle
              label="Automatically check for updates"
              on={updateCheck}
              onChange={(on) => {
                setUpdateCheck(on);
                if (on && !engine?.update) send({ cmd: "update.check" });
              }}
            />
            <span className="text-[0.7rem] text-text-2 block">
              Checks the public GitHub releases once a day, from the hub. No telemetry is sent.
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn" disabled={isPending("update.check")} onClick={() => send({ cmd: "update.check" })}>
                {isPending("update.check") ? "Checking…" : "Check now"}
              </button>
              {engine?.update?.available && (
                <button className="btn btn-primary" onClick={() => openDialog("update")}>
                  Update to v{engine.update.latest}
                </button>
              )}
              <span className="text-[0.7rem] text-text-2">
                {engine?.version && `v${engine.version}`}
                {engine?.update && !engine.update.available && " · up to date"}
              </span>
            </div>
          </div>
        )}
        <button
          className="btn btn-primary w-full"
          disabled={saving}
          onClick={() => {
            sent.current = true;
            send({ cmd: "settings.update", patch: { notifiers, update_check: updateCheck, mqtt } });
          }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {engine?.mode === "hub" && (
          <div className="hairline pt-4 space-y-3">
            <div>
              <span className="label block">API &amp; MCP access</span>
              <span className="text-[0.7rem] text-text-2 block mt-1">
                Bearer tokens for the REST API and MCP server. Scopes are cumulative: read ⊂ control ⊂ manage.
              </span>
            </div>

            {createdToken && (
              <div className="relative rounded border border-accent/40 bg-accent/5 p-3 pr-8 space-y-2">
                <button
                  className="absolute top-2 right-2 text-text-2 hover:text-accent text-lg leading-none cursor-pointer"
                  onClick={clearCreatedToken}
                  aria-label="Dismiss"
                >
                  ×
                </button>
                <span className="text-[0.7rem] text-text-1 block">
                  Copy <span className="text-accent">{createdToken.name}</span> now — it is shown once and cannot be retrieved later.
                </span>
                <div className="flex items-center gap-2">
                  <code className="mono text-[0.68rem] text-text-0 break-all flex-1">{createdToken.secret}</code>
                  <button className="btn" onClick={() => navigator.clipboard?.writeText(createdToken.secret)}>
                    Copy
                  </button>
                </div>
              </div>
            )}

            {tokens.length > 0 && (
              <div className="space-y-2">
                {tokens.map((t) => (
                  <div key={t.id} className="flex items-center gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-text-0 truncate">{t.name}</span>
                        <span className="chip chip-accent">{t.scope}</span>
                      </div>
                      <span className="mono text-[0.65rem] text-text-2 block truncate">{t.hint}</span>
                    </div>
                    <button
                      className="btn btn-danger"
                      disabled={isPending("token.remove")}
                      onClick={() => send({ cmd: "token.remove", id: t.id })}
                    >
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-2">
              <input
                className="field"
                placeholder="Token name"
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
              />
              <div className="flex gap-2">
                <select className="field" value={tokenScope} onChange={(e) => setTokenScope(e.target.value as ApiToken["scope"])}>
                  <option value="read">read</option>
                  <option value="control">control</option>
                  <option value="manage">manage</option>
                </select>
                <button
                  className="btn btn-primary whitespace-nowrap"
                  disabled={!tokenName.trim() || isPending("token.create")}
                  onClick={() => {
                    send({ cmd: "token.create", name: tokenName.trim(), scope: tokenScope });
                    setTokenName("");
                  }}
                >
                  {isPending("token.create") ? "…" : "Generate"}
                </button>
              </div>
            </div>
          </div>
        )}
        <div className="hairline pt-4 flex items-center justify-between">
          <span className="text-xs text-text-1">
            Mode: <span className="mono text-accent">{engine?.mode}</span>
          </span>
          <button className="btn" onClick={leaveMode}>
            Switch mode
          </button>
        </div>
      </div>
    </Dialog>
  );
}
