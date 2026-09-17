import { useEffect, useId, useRef } from "react";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { Modal } from "./Dialog";
import { Feed } from "./Feed";
import { DeviceChip } from "./MonitorTile";
import { NameField } from "./NameField";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { PrinterControls } from "./PrinterControls";
import { RiskGauge } from "./RiskGauge";
import { SaveStatus } from "./SaveStatus";
import { Slider } from "./Slider";
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

export function DetailPanel({ monitor }: { monitor: Monitor }) {
  const { engine, history, send, openDetail, openStats, openDialog, isPending, updateMonitor } = useStore();
  const settingsPanels = usePluginSurface("settings", monitor.id);
  const titleId = useId();
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
  const close = () => openDetail(null);

  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in h-full w-full sm:w-[460px] bg-ink-1 border-l border-line-0 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-ink-1/95 backdrop-blur-sm flex items-center gap-2.5 px-5 py-3.5 border-b border-line-0">
          <span
            aria-hidden
            className={`led ${monitor.alert ? "led-bad" : monitor.watching && camera?.online ? "led-on" : "led-off"}`}
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
              defect at {(monitor.alert.score * 100).toFixed(0)}%, action {monitor.alert.action}
            </p>
          )}
          <button className="btn w-full mt-3" onClick={() => openStats(monitor.id)}>
            View detailed history
          </button>
        </Section>

        {printer && (
          <Section title="Printer control">
            <PrinterControls printer={printer} />
          </Section>
        )}

        <Section title="Monitoring">
          <div className="space-y-4">
            <NameField name={monitor.name} onRename={(name) => updateMonitor(monitor.id, { name })} />
            <Toggle label="Watch this monitor" on={monitor.enabled} onChange={(v) => updateMonitor(monitor.id, { enabled: v })} />
            {monitor.enabled && monitor.watching === false && (
              <p className="mono text-[0.7rem] text-text-2">
                standby, printer is {printer?.device_state?.status ?? "not printing"}, inference resumes when it prints
              </p>
            )}
            {monitor.enabled && monitor.watching !== false && printer && !printer.online && (
              <p className="mono text-[0.7rem] text-text-2">
                watching, the printer reports {printer.device_state?.status ?? "nothing yet"}, so inference runs until it says it is
                not printing
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
            <Slider
              label="Alert threshold"
              value={monitor.threshold}
              min={0.05}
              max={1}
              step={0.01}
              hint="The score a frame must reach to count as a defect. Raise to cut false alarms; lower to catch subtler failures."
              onChange={(v) => updateMonitor(monitor.id, { threshold: v })}
            />
            <Slider
              label="Consecutive detections to alert"
              value={monitor.consecutive}
              min={1}
              max={15}
              step={1}
              format={String}
              hint="Flagged frames in a row before it acts. Raise to ride out brief blips; lower to react faster."
              onChange={(v) => updateMonitor(monitor.id, { consecutive: v })}
            />
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
            <Slider
              label="Cooldown (seconds)"
              value={monitor.cooldown_s}
              min={0}
              max={600}
              step={10}
              format={String}
              hint="Quiet gap after acting before it can act again. Raise to avoid repeat alerts on one failure."
              onChange={(v) => updateMonitor(monitor.id, { cooldown_s: v })}
            />
            <Toggle label="Push notifications" on={monitor.notify} onChange={(v) => updateMonitor(monitor.id, { notify: v })} />
          </div>
        </Section>

        {settingsPanels.map(({ plugin, node }) => (
          <Section key={plugin.id} title={plugin.manifest.name}>
            <PluginNodeView plugin={plugin} node={node} />
          </Section>
        ))}

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
