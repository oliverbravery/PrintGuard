import { useEffect, useState } from "react";
import { useStore } from "../store";
import { applyTheme, beginPreview, endPreview, PALETTES } from "../theme";
import type { ApiToken, CustomTheme, MqttConfig, ThemeBase, ThemeTokenKey } from "../types";
import { Dialog } from "./Dialog";
import { SaveStatus } from "./SaveStatus";
import { SchemaForm } from "./SchemaForm";
import { ThemeEditor } from "./ThemeEditor";
import { Toggle } from "./Toggle";

type TabId = "appearance" | "alerts" | "mqtt" | "updates" | "api";

const SCHEMES: { id: string; name: string; glyph: string }[] = [
  { id: "system", name: "System", glyph: "◐" },
  { id: "light", name: "Light", glyph: "☀" },
  { id: "dark", name: "Dark", glyph: "☾" },
];

function Swatch({ colors }: { colors: CustomTheme["colors"] }) {
  return (
    <span className="flex overflow-hidden rounded border border-line-1">
      {(["ink0", "accent", "ok", "bad"] as ThemeTokenKey[]).map((k) => (
        <span key={k} className="h-4 w-4" style={{ background: colors[k] }} />
      ))}
    </span>
  );
}

export function SettingsDialog() {
  const { engine, send, openDialog, leaveMode, isPending, notifyTest, testingNotifier, testNotifier, createdToken, clearCreatedToken, updateSettings } = useStore();
  const [notifiers, setNotifiers] = useState(engine?.settings.notifiers ?? {});
  const updateCheck = engine?.settings.update_check ?? true;
  const [mqtt, setMqtt] = useState<MqttConfig>(engine?.settings.mqtt ?? {});
  const setMqttField = (key: keyof MqttConfig, value: MqttConfig[keyof MqttConfig]) => setMqtt({ ...mqtt, [key]: value });
  const [tokenName, setTokenName] = useState("");
  const [tokenScope, setTokenScope] = useState<ApiToken["scope"]>("read");
  const [tab, setTab] = useState<TabId>("alerts");
  const close = () => openDialog(null);
  const tokens = engine?.tokens ?? [];

  const theme = engine?.settings.theme ?? "system";
  const themes = engine?.settings.themes ?? [];
  const [editing, setEditing] = useState<CustomTheme | null>(null);

  const upsertTheme = (list: CustomTheme[], t: CustomTheme) =>
    list.some((x) => x.id === t.id) ? list.map((x) => (x.id === t.id ? t : x)) : [...list, t];
  const selectTheme = (id: string) => {
    applyTheme(id, themes, true);
    send({ cmd: "settings.update", patch: { theme: id } });
  };
  const newTheme = (base: ThemeBase) =>
    setEditing({ id: "t" + Date.now().toString(36), name: "", base, colors: { ...PALETTES[base] } });
  const cancelEdit = () => {
    endPreview();
    setEditing(null);
    applyTheme(theme, themes, true);
  };
  const saveTheme = () => {
    if (!editing) return;
    const next = upsertTheme(themes, { ...editing, name: editing.name.trim() || "Custom" });
    endPreview();
    applyTheme(editing.id, next, true);
    send({ cmd: "settings.update", patch: { themes: next, theme: editing.id } });
    setEditing(null);
  };
  const deleteTheme = (id: string) => {
    const next = themes.filter((t) => t.id !== id);
    const selection = theme === id ? "system" : theme;
    applyTheme(selection, next, true);
    send({ cmd: "settings.update", patch: { themes: next, theme: selection } });
  };

  useEffect(() => {
    if (!editing) return;
    beginPreview();
    applyTheme(editing.id, upsertTheme(themes, editing), true);
  }, [editing]);

  const channels = (engine?.notifiers ?? []).filter((n) => engine?.mode === "hub" || n.browser_ok);

  const tabs: { id: TabId; label: string }[] = [
    { id: "appearance", label: "Appearance" },
    { id: "alerts", label: "Alerts" },
    ...(engine?.mode === "hub"
      ? ([
          { id: "mqtt", label: "Home Assistant" },
          { id: "updates", label: "Updates" },
          { id: "api", label: "API" },
        ] as const)
      : []),
  ];

  const onTabKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const i = tabs.findIndex((t) => t.id === tab);
    let next = i;
    if (delta) next = (i + delta + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    setTab(tabs[next].id);
    document.getElementById(`settings-tab-${tabs[next].id}`)?.focus();
  };

  return (
    <Dialog title="Settings" onClose={close}>
      <div className="space-y-5">
        {tabs.length > 1 && (
          <div
            role="tablist"
            aria-label="Settings sections"
            onKeyDown={onTabKeyDown}
            className="flex gap-1 border-b border-line-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {tabs.map((t) => (
              <button
                key={t.id}
                id={`settings-tab-${t.id}`}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                aria-controls={`settings-panel-${t.id}`}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setTab(t.id)}
                className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-xs transition-colors cursor-pointer ${
                  tab === t.id ? "border-accent text-text-0" : "border-transparent text-text-2 hover:text-text-1"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {tab === "appearance" && (
          <div role="tabpanel" id="settings-panel-appearance" aria-labelledby="settings-tab-appearance" tabIndex={0}>
            {editing ? (
            <ThemeEditor
              value={editing}
              onChange={setEditing}
              onSave={saveTheme}
              onCancel={cancelEdit}
              canSave={!!editing.name.trim()}
            />
          ) : (
            <div className="space-y-4">
              <span className="label block">Theme</span>
              <div className="grid grid-cols-3 gap-2">
                {SCHEMES.map((opt) => (
                  <button
                    key={opt.id}
                    onClick={() => selectTheme(opt.id)}
                    className={`flex flex-col items-center gap-1 rounded border px-2 py-3 transition-colors cursor-pointer ${
                      theme === opt.id ? "border-accent bg-accent/5 text-text-0" : "border-line-0 text-text-1 hover:border-line-1"
                    }`}
                  >
                    <span className="text-base leading-none">{opt.glyph}</span>
                    <span className="text-xs">{opt.name}</span>
                  </button>
                ))}
              </div>

              <div className="flex items-center justify-between">
                <span className="label block">Custom themes</span>
                <button className="btn" onClick={() => newTheme(theme === "light" ? "light" : "dark")}>
                  + New
                </button>
              </div>
              {themes.length === 0 && (
                <span className="block text-[0.7rem] text-text-2">No custom themes yet. Create one to tailor every colour.</span>
              )}
              <div className="space-y-2">
                {themes.map((t) => (
                  <div key={t.id} className="flex items-center gap-2">
                    <button
                      onClick={() => selectTheme(t.id)}
                      className={`flex flex-1 items-center gap-2 overflow-hidden rounded border px-3 py-2 text-left transition-colors cursor-pointer ${
                        theme === t.id ? "border-accent bg-accent/5" : "border-line-0 hover:border-line-1"
                      }`}
                    >
                      <Swatch colors={t.colors} />
                      <span className="flex-1 truncate text-xs text-text-0">{t.name}</span>
                      <span className="chip">{t.base}</span>
                    </button>
                    <button className="btn" onClick={() => setEditing({ ...t, colors: { ...t.colors } })}>
                      Edit
                    </button>
                    <button className="btn btn-danger" onClick={() => deleteTheme(t.id)}>
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            </div>
            )}
          </div>
        )}

        {tab === "alerts" && (
          <div role="tabpanel" id="settings-panel-alerts" aria-labelledby="settings-tab-alerts" tabIndex={0} className="space-y-4">
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
            <button
              className="btn btn-primary w-full"
              disabled={isPending("settings.update")}
              onClick={() => send({ cmd: "settings.update", patch: { notifiers } })}
            >
              {isPending("settings.update") ? "Saving…" : "Save channels"}
            </button>
            <span className="text-[0.7rem] text-text-2 block">
              Channels hold credentials, so they apply on Save rather than automatically.
            </span>
          </div>
        )}

        {tab === "mqtt" && (
          <div role="tabpanel" id="settings-panel-mqtt" aria-labelledby="settings-tab-mqtt" tabIndex={0} className="space-y-3">
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
            <button
              className="btn btn-primary w-full"
              disabled={isPending("settings.update")}
              onClick={() => send({ cmd: "settings.update", patch: { mqtt } })}
            >
              {isPending("settings.update") ? "Saving…" : "Save broker settings"}
            </button>
            <span className="text-[0.7rem] text-text-2 block">
              Broker settings open a live connection, so they apply on Save rather than automatically.
            </span>
          </div>
        )}

        {tab === "updates" && (
          <div role="tabpanel" id="settings-panel-updates" aria-labelledby="settings-tab-updates" tabIndex={0} className="space-y-3">
            <span className="label block">Software updates</span>
            <Toggle
              label="Automatically check for updates"
              on={updateCheck}
              onChange={(on) => {
                updateSettings({ update_check: on });
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
            <div className="flex justify-end">
              <SaveStatus />
            </div>
          </div>
        )}

        {tab === "api" && (
          <div role="tabpanel" id="settings-panel-api" aria-labelledby="settings-tab-api" tabIndex={0} className="space-y-3">
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
          {engine?.mode === "local" && (
            <button className="btn" onClick={leaveMode}>
              Back to start
            </button>
          )}
        </div>
      </div>
    </Dialog>
  );
}
