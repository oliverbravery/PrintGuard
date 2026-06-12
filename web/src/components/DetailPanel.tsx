import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { Printer } from "../types";
import { Feed } from "./Feed";
import { DeviceChip } from "./PrinterTile";
import { RiskGauge } from "./RiskGauge";
import { SchemaForm } from "./SchemaForm";
import { Sparkline } from "./Sparkline";
import { Toggle } from "./Toggle";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="px-5 py-4 border-b border-line-0">
      <h3 className="display text-[0.68rem] font-semibold tracking-[0.24em] text-text-2 mb-3">{title}</h3>
      {children}
    </section>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <div className="flex justify-between mb-1">
        <span className="label">{label}</span>
        <span className="mono text-[0.72rem] text-text-0">{value.toFixed(2)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function DetailPanel({ printer }: { printer: Printer }) {
  const { engine, history, send, openDetail, deviceTest, testing, testDevice, isPending } = useStore();
  const [draft, setDraft] = useState(printer);
  const actionRef = useRef<string | null>(null);
  const saveRef = useRef<string | null>(null);
  useEffect(() => setDraft(printer), [printer.id]);

  const updating = isPending("printer.update");
  const removing = isPending("printer.remove");

  useEffect(() => {
    if (saveRef.current === "printer.update" && !updating) close();
    if (saveRef.current === "printer.remove" && !removing) close();
  }, [updating, removing]);

  const camera = engine?.cameras.find((c) => c.id === printer.camera_id);
  const points = history[printer.id] ?? [];
  const score = points.at(-1)?.score ?? 0;
  const integrations = engine?.integrations ?? [];
  const meta = integrations.find((i) => i.id === draft.device.provider);
  const linked = Boolean(printer.device.provider);
  const close = () => openDetail(null);

  const patch = (fields: Partial<Printer>) => setDraft((d) => ({ ...d, ...fields }));
  const patchDevice = (fields: Partial<Printer["device"]>) => setDraft((d) => ({ ...d, device: { ...d.device, ...fields } }));

  return (
    <div className="backdrop" onClick={close}>
      <aside
        className="slide-in fixed right-0 top-0 h-full w-full sm:w-[460px] bg-ink-1 border-l border-line-0 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 bg-ink-1/95 backdrop-blur-sm flex items-center gap-2.5 px-5 py-3.5 border-b border-line-0">
          <span className={`led ${printer.alert ? "led-bad" : camera?.inferring ? "led-infer" : printer.enabled && camera?.online ? "led-on" : "led-off"}`} />
          <h2 className="display text-lg font-semibold flex-1 truncate">{printer.name}</h2>
          <DeviceChip state={printer.device_state} />
          <button className="text-text-2 hover:text-accent text-2xl leading-none cursor-pointer" onClick={close}>
            ×
          </button>
        </div>

        <Feed camera={camera} mode={engine?.mode ?? "local"} whep={engine?.settings.whep_base ?? ""} />

        <Section title="Live risk">
          <div className="flex items-center gap-4">
            <RiskGauge score={score} threshold={printer.threshold} size={84} />
            <div className="flex-1">
              <Sparkline points={points} threshold={printer.threshold} />
            </div>
          </div>
          {printer.alert && (
            <p className="mono text-[0.7rem] text-bad mt-2">
              defect at {(printer.alert.score * 100).toFixed(0)}% — action: {printer.alert.action}
            </p>
          )}
        </Section>

        {linked && (
          <Section title="Printer control">
            <div className="grid grid-cols-3 gap-2">
              {(["pause", "resume", "cancel"] as const).map((action) => {
                const busy = isPending("printer.action");
                return (
                  <button
                    key={action}
                    className={`btn ${action === "cancel" ? "btn-danger" : ""}`}
                    disabled={busy}
                    onClick={() => {
                      actionRef.current = action;
                      send({ cmd: "printer.action", id: printer.id, action });
                    }}
                  >
                    {busy && actionRef.current === action ? `${action}…` : action}
                  </button>
                );
              })}
            </div>
            {printer.device_state?.job && (
              <p className="mono text-[0.68rem] text-text-2 mt-2 truncate">job: {printer.device_state.job}</p>
            )}
          </Section>
        )}

        <Section title="Monitoring">
          <div className="space-y-4">
            <Toggle label="Watch this printer" on={draft.enabled} onChange={(v) => patch({ enabled: v })} />
            <label className="block">
              <span className="label block mb-1">Camera</span>
              <select className="field" value={draft.camera_id} onChange={(e) => patch({ camera_id: e.target.value })}>
                <option value="">No camera</option>
                {(engine?.cameras ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <Slider label="Alert threshold" value={draft.threshold} min={0.05} max={1} step={0.01} onChange={(v) => patch({ threshold: v })} />
            <Slider label="Sensitivity" value={draft.sensitivity} min={0.2} max={5} step={0.1} onChange={(v) => patch({ sensitivity: v })} />
            <label className="block">
              <div className="flex justify-between mb-1">
                <span className="label">Consecutive detections to alert</span>
                <span className="mono text-[0.72rem]">{draft.consecutive}</span>
              </div>
              <input
                type="range"
                min={1}
                max={15}
                step={1}
                value={draft.consecutive}
                onChange={(e) => patch({ consecutive: Number(e.target.value) })}
              />
            </label>
          </div>
        </Section>

        <Section title="Defect response">
          <div className="space-y-4">
            <label className="block">
              <span className="label block mb-1">On sustained defect</span>
              <select className="field" value={draft.device.on_defect} onChange={(e) => patchDevice({ on_defect: e.target.value as Printer["device"]["on_defect"] })}>
                <option value="none">Alert only</option>
                <option value="pause">Pause the print</option>
                <option value="cancel">Cancel the print</option>
              </select>
            </label>
            <label className="block">
              <div className="flex justify-between mb-1">
                <span className="label">Cooldown (seconds)</span>
                <span className="mono text-[0.72rem]">{draft.device.cooldown_s}</span>
              </div>
              <input
                type="range"
                min={0}
                max={600}
                step={10}
                value={draft.device.cooldown_s}
                onChange={(e) => patchDevice({ cooldown_s: Number(e.target.value) })}
              />
            </label>
            <Toggle label="Push notifications" on={draft.notify} onChange={(v) => patch({ notify: v })} />
          </div>
        </Section>

        <Section title="Printer service">
          <div className="space-y-4">
            <select
              className="field"
              value={draft.device.provider ?? ""}
              onChange={(e) => patchDevice({ provider: e.target.value || null, config: {} })}
            >
              <option value="">Not linked</option>
              {integrations.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.label}
                </option>
              ))}
            </select>
            {meta && (
              <>
                <SchemaForm meta={meta} value={draft.device.config} onChange={(config) => patchDevice({ config })} />
                <div className="flex items-center gap-3">
                  <button className="btn" disabled={testing} onClick={() => testDevice(meta.id, draft.device.config)}>
                    {testing ? "Testing…" : "Test connection"}
                  </button>
                  {deviceTest && (
                    <span className={`chip ${deviceTest.ok ? "chip-ok" : "chip-bad"}`}>
                      {deviceTest.ok ? `ok — ${deviceTest.status}` : deviceTest.error || deviceTest.status || "failed"}
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        </Section>

        <div className="px-5 py-4 flex gap-2.5">
          <button
            className="btn btn-primary flex-1"
            disabled={updating}
            onClick={() => {
              saveRef.current = "printer.update";
              send({ cmd: "printer.update", id: printer.id, patch: draft });
            }}
          >
            {updating ? "Saving…" : "Save"}
          </button>
          <button
            className="btn btn-danger"
            disabled={removing}
            onClick={() => {
              saveRef.current = "printer.remove";
              send({ cmd: "printer.remove", id: printer.id });
            }}
          >
            {removing ? "Deleting…" : "Delete"}
          </button>
        </div>
      </aside>
    </div>
  );
}
