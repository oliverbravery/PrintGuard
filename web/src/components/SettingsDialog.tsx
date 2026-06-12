import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Dialog } from "./Dialog";
import { SchemaForm } from "./SchemaForm";
import { Toggle } from "./Toggle";

export function SettingsDialog() {
  const { engine, send, openDialog, leaveMode, isPending, notifyTest, testingNotifier, testNotifier } = useStore();
  const [notifiers, setNotifiers] = useState(engine?.settings.notifiers ?? {});
  const [whep, setWhep] = useState(engine?.settings.whep_base ?? "");
  const saving = isPending("settings.update");
  const sent = useRef(false);
  const close = () => openDialog(null);

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
          <label className="block">
            <span className="label block mb-1">WebRTC base URL</span>
            <input
              className="field"
              placeholder={`${location.protocol}//${location.hostname}:8889`}
              value={whep}
              onChange={(e) => setWhep(e.target.value)}
            />
            <span className="text-[0.7rem] text-text-2 block mt-1">
              Where browsers reach MediaMTX for live playback. Leave blank for the default.
            </span>
          </label>
        )}
        <button
          className="btn btn-primary w-full"
          disabled={saving}
          onClick={() => {
            sent.current = true;
            send({ cmd: "settings.update", patch: { notifiers, whep_base: whep.trim() } });
          }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
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
