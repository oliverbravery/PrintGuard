import { useRef, useState } from "react";
import { savedChannels, useStore } from "../store";
import { useSubmit } from "../submit";
import type { AdapterConfig, AdapterMeta } from "../types";
import { retypeReason, SchemaForm, savedSecretTitles } from "./SchemaForm";
import { Slider } from "./Slider";
import { TestRow } from "./TestRow";
import { Toggle } from "./Toggle";

export function AlertsTab() {
  const { engine, isPending, notifyTest, testingNotifier, testNotifier, updateSettings } = useStore();
  const [notifiers, setNotifiers] = useState(() => savedChannels(engine));
  const parkedChannels = useRef<Record<string, AdapterConfig>>({});
  const saveChannels = useSubmit(() => {
    parkedChannels.current = {};
    setNotifiers(savedChannels(engine));
  });
  const desktopApp = "pywebview" in window;
  const channels = (engine?.notifiers ?? []).filter((n) => !n.desktop_only || desktopApp);
  const channelRetype = (meta: AdapterMeta) => {
    const stored = engine?.settings.notifiers[meta.id];
    return meta.id in notifiers && stored ? retypeReason(notifiers[meta.id], stored, savedSecretTitles(meta, engine?.secrets_set?.notifiers[meta.id] ?? [])) : null;
  };
  return (
    <div className="space-y-4">
      <span className="label block">When to alert</span>
      <Slider
        label="Fault grace period (seconds)"
        value={engine?.settings.fault_grace_s ?? 120}
        min={30}
        max={900}
        step={30}
        format={String}
        onChange={(v) => updateSettings({ fault_grace_s: v })}
        hint="How long a camera or printer fault has to last before PrintGuard sends a warning. Bump this up if a Wi-Fi camera occasionally drops out and reconnects."
      />
      <span className="label block">Notification channels</span>
      {channels.map((meta) => {
        const enabled = meta.id in notifiers;
        const target = JSON.stringify([meta.id, notifiers[meta.id]]);
        return (
          <div key={meta.id} className="space-y-3 border-t border-line-0 pt-3">
            <Toggle
              label={meta.label}
              on={enabled}
              onChange={(on) => {
                const next = { ...notifiers };
                if (on) next[meta.id] = parkedChannels.current[meta.id] ?? {};
                else {
                  parkedChannels.current[meta.id] = next[meta.id];
                  delete next[meta.id];
                }
                setNotifiers(next);
              }}
            />
            {enabled && (
              <>
                <SchemaForm
                  meta={meta}
                  value={notifiers[meta.id]}
                  stored={engine?.settings.notifiers[meta.id]}
                  saved={engine?.secrets_set?.notifiers[meta.id]}
                  onChange={(config) => setNotifiers({ ...notifiers, [meta.id]: config })}
                />
                <TestRow
                  label="Send test alert"
                  busyLabel="Sending…"
                  busy={testingNotifier === target}
                  disabled={testingNotifier !== null}
                  onTest={() => testNotifier(target, meta.id, notifiers[meta.id])}
                  result={
                    notifyTest?.target === target
                      ? { ok: notifyTest.ok, message: notifyTest.ok ? "sent" : notifyTest.error || "failed" }
                      : null
                  }
                />
                {channelRetype(meta) && <span className="block text-sm text-text-2">{channelRetype(meta)}</span>}
              </>
            )}
          </div>
        );
      })}
      <span className="block text-sm text-text-2">
        Defect alerts (with a snapshot) go to every enabled channel for monitors that have push notifications switched on.
      </span>
      <button
        className="btn btn-primary"
        disabled={isPending("settings.update") || channels.some(channelRetype)}
        onClick={() => saveChannels.submit({ cmd: "settings.update", patch: { notifiers } })}
      >
        {isPending("settings.update") ? "Saving…" : "Save channels"}
      </button>
      {saveChannels.error && (
        <span role="alert" className="chip chip-message chip-bad">
          {saveChannels.error}
        </span>
      )}
      <span className="block text-sm text-text-2">
        Channels store credentials, so changes apply once you click Save.
      </span>
    </div>
  );
}
