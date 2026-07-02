import { useEffect, useId, useRef } from "react";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { Modal } from "./Dialog";
import { Feed } from "./Feed";
import { DeviceChip } from "./MonitorTile";
import { RiskGauge } from "./RiskGauge";
import { SaveStatus } from "./SaveStatus";
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

export function DetailPanel({ monitor }: { monitor: Monitor }) {
  const { engine, history, send, openDetail, openStats, openDialog, isPending, updateMonitor } = useStore();
  const titleId = useId();
  const actionRef = useRef<string | null>(null);
  const removeRef = useRef(false);
  const removing = isPending("monitor.remove");

  useEffect(() => {
    if (removeRef.current && !removing) close();
  }, [removing]);

  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const printers = engine?.printers ?? [];
  const points = history[monitor.id] ?? [];
  const score = points.at(-1)?.score ?? 0;
  const linked = Boolean(printer);
  const close = () => openDetail(null);

  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in h-full w-full sm:w-[460px] bg-ink-1 border-l border-line-0 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-ink-1/95 backdrop-blur-sm flex items-center gap-2.5 px-5 py-3.5 border-b border-line-0">
          <span
            aria-hidden
            className={`led ${monitor.alert ? "led-bad" : camera?.inferring ? "led-infer" : monitor.watching && camera?.online ? "led-on" : "led-off"}`}
          />
          <h2 id={titleId} className="display text-lg font-semibold flex-1 truncate">
            {monitor.name}
          </h2>
          <DeviceChip state={printer?.device_state ?? undefined} />
          <button
            type="button"
            className="text-text-2 hover:text-accent text-2xl leading-none cursor-pointer"
            onClick={close}
            aria-label="Close monitor details"
          >
            ×
          </button>
        </div>

        <Feed camera={camera} mode={engine?.mode ?? "local"} />

        <Section title="Live risk">
          <div className="flex items-center gap-4">
            <RiskGauge score={score} threshold={monitor.threshold} size={84} />
            <div className="flex-1">
              <Sparkline points={points} threshold={monitor.threshold} />
            </div>
          </div>
          {monitor.alert && (
            <p className="mono text-[0.7rem] text-bad mt-2">
              defect at {(monitor.alert.score * 100).toFixed(0)}% — action: {monitor.alert.action}
            </p>
          )}
          <button className="btn w-full mt-3" onClick={() => openStats(monitor.id)}>
            View detailed history
          </button>
        </Section>

        {linked && printer && (
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
            <Toggle label="Watch this monitor" on={monitor.enabled} onChange={(v) => updateMonitor(monitor.id, { enabled: v })} />
            {monitor.enabled && monitor.watching === false && (
              <p className="mono text-[0.7rem] text-text-2">
                standby — printer is {printer?.device_state?.status ?? "not printing"}; inference resumes when it prints
              </p>
            )}
            <label className="block">
              <span className="label block mb-1">Camera</span>
              <select className="field" value={monitor.camera_id} onChange={(e) => updateMonitor(monitor.id, { camera_id: e.target.value })}>
                <option value="">No camera</option>
                {(engine?.cameras ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <Slider label="Alert threshold" value={monitor.threshold} min={0.05} max={1} step={0.01} onChange={(v) => updateMonitor(monitor.id, { threshold: v })} />
            <Slider label="Sensitivity" value={monitor.sensitivity} min={0.2} max={5} step={0.1} onChange={(v) => updateMonitor(monitor.id, { sensitivity: v })} />
            <label className="block">
              <div className="flex justify-between mb-1">
                <span className="label">Consecutive detections to alert</span>
                <span className="mono text-[0.72rem]">{monitor.consecutive}</span>
              </div>
              <input
                type="range"
                min={1}
                max={15}
                step={1}
                value={monitor.consecutive}
                onChange={(e) => updateMonitor(monitor.id, { consecutive: Number(e.target.value) })}
              />
            </label>
          </div>
        </Section>

        <Section title="Defect response">
          <div className="space-y-4">
            <label className="block">
              <span className="label block mb-1">On sustained defect</span>
              <select className="field" value={monitor.on_defect} onChange={(e) => updateMonitor(monitor.id, { on_defect: e.target.value as Monitor["on_defect"] })}>
                <option value="none">Alert only</option>
                <option value="pause">Pause the print</option>
                <option value="cancel">Cancel the print</option>
              </select>
            </label>
            <label className="block">
              <div className="flex justify-between mb-1">
                <span className="label">Cooldown (seconds)</span>
                <span className="mono text-[0.72rem]">{monitor.cooldown_s}</span>
              </div>
              <input
                type="range"
                min={0}
                max={600}
                step={10}
                value={monitor.cooldown_s}
                onChange={(e) => updateMonitor(monitor.id, { cooldown_s: Number(e.target.value) })}
              />
            </label>
            <Toggle label="Push notifications" on={monitor.notify} onChange={(v) => updateMonitor(monitor.id, { notify: v })} />
          </div>
        </Section>

        <Section title="Printer">
          <div className="space-y-3">
            <select className="field" value={monitor.printer_id} onChange={(e) => updateMonitor(monitor.id, { printer_id: e.target.value })}>
              <option value="">No printer (alerts only)</option>
              {printers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button className="btn w-full !py-1.5" onClick={() => openDialog("printers")}>
              Manage printer registry
            </button>
          </div>
        </Section>

        <div className="px-5 py-4 flex items-center gap-2.5">
          <SaveStatus />
          <div className="flex-1" />
          <button
            className="btn btn-danger"
            disabled={removing}
            onClick={() => {
              removeRef.current = true;
              send({ cmd: "monitor.remove", id: monitor.id });
            }}
          >
            {removing ? "Deleting…" : "Delete"}
          </button>
        </div>
      </aside>
    </Modal>
  );
}
