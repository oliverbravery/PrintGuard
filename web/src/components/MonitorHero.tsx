import { useState } from "react";
import { Link } from "react-router";
import { sourceLabel } from "../cameras";
import { alertOutcome } from "../history";
import { awaitingReview, framesLabel } from "../review";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { Feed, useCovered } from "./Feed";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { activeJob, HeaterReadouts, jobText, PreheatPane, PrintActions, ProgressBar } from "./PrinterControls";
import { RiskMeter } from "./RiskMeter";
import { SaveStatus } from "./SaveStatus";
import { Segmented } from "./Segmented";
import { Slider } from "./Slider";
import { Sparkline } from "./Sparkline";
import { DeviceStatus, monitorState, Status } from "./Status";
import { TabPanel, Tabs } from "./Tabs";

type Pane = "control" | "tune" | "preheat";

const PANES: { id: Pane; label: string }[] = [
  { id: "control", label: "Control" },
  { id: "tune", label: "Tune" },
  { id: "preheat", label: "Preheat" },
];

const RESPONSES: { value: Monitor["on_defect"]; label: string }[] = [
  { value: "none", label: "Alert" },
  { value: "pause", label: "Pause" },
  { value: "cancel", label: "Cancel" },
];

function Block({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`border-b border-line-0 px-4 py-3 ${className}`}>{children}</div>;
}

function ControlPane({ monitor }: { monitor: Monitor }) {
  const { engine, history } = useStore();
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const device = printer?.device_state;
  const awaiting = awaitingReview(engine?.reviews ?? [], monitor.id);
  const score = camera?.online && monitor.watching ? (history[monitor.id]?.at(-1)?.score ?? 0) : null;
  const state = monitorState(monitor, Boolean(camera?.online));
  return (
    <>
      <Block>
        <div className="flex items-center justify-between gap-2">
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Status tone={state.tone}>{state.text}</Status>
            <DeviceStatus state={device} />
          </span>
          <Link to={`/monitors/${monitor.id}/edit`} className="btn-inline">
            Edit
          </Link>
        </div>
        <h2 className="mt-1 truncate text-xl font-bold tracking-[-0.02em]">{monitor.name}</h2>
        <p className="mono truncate text-xs text-text-1">
          {activeJob(device) ? jobText(device) : printer ? `${printer.name}, ${printer.device_state?.status ?? "no status yet"}` : "No printer, alerts only"}
        </p>
      </Block>
      <Block>
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="label">Defect risk</span>
          <Link to={`/monitors/${monitor.id}/history`} className="btn-inline">
            History
          </Link>
        </div>
        <RiskMeter score={score} threshold={monitor.threshold} size="hero" />
        <div className="mt-2">
          <Sparkline points={history[monitor.id] ?? []} threshold={monitor.threshold} />
        </div>
        {monitor.alert && (
          <p className="mono mt-2 text-xs text-bad">
            {[`defect at ${(monitor.alert.score * 100).toFixed(0)}%`, alertOutcome(monitor.alert.action)].filter(Boolean).join(", ")}
          </p>
        )}
      </Block>
      {awaiting && (
        <Block className="flex items-center justify-between gap-3 bg-ink-1 py-2">
          <span className="text-sm font-semibold">{framesLabel(awaiting.frames)} from the last print</span>
          <Link to={`/monitors/${monitor.id}/review/${awaiting.id}`} className="btn-inline btn-inline-accent">
            Review
          </Link>
        </Block>
      )}
      {printer ? (
        <>
          <div className="flex-1 border-b border-rule">
            <HeaterReadouts state={device} />
          </div>
          <PrintActions printer={printer} />
        </>
      ) : (
        <p className="mt-auto border-t border-rule px-4 py-3 text-sm text-text-1">Bind a printer to pause or cancel a failing print.</p>
      )}
    </>
  );
}

function TunePane({ monitor }: { monitor: Monitor }) {
  const updateMonitor = useStore((s) => s.updateMonitor);
  return (
    <>
      <Block>
        <Slider
          label="Alert threshold"
          value={monitor.threshold}
          min={0.05}
          max={0.95}
          step={0.01}
          hint="The score a frame must reach to count as a defect. Raise to cut false alarms. Lower to catch subtler failures."
          onChange={(v) => updateMonitor(monitor.id, { threshold: v })}
        />
      </Block>
      <Block>
        <Slider
          label="Consecutive detections to alert"
          value={monitor.consecutive}
          min={1}
          max={30}
          step={1}
          format={String}
          hint="Flagged frames in a row before it acts. Raise to ride out brief blips. Lower to react faster."
          onChange={(v) => updateMonitor(monitor.id, { consecutive: v })}
        />
      </Block>
      <Block>
        <Segmented label="On sustained defect" options={RESPONSES} value={monitor.on_defect} onChange={(v) => updateMonitor(monitor.id, { on_defect: v })} />
      </Block>
      <Block>
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
      </Block>
      <div className="mt-auto flex items-center justify-between gap-2 px-4 py-2">
        <SaveStatus scope={`monitor:${monitor.id}`} />
        <Link to={`/monitors/${monitor.id}/edit`} className="btn-inline">
          Monitor settings
        </Link>
      </div>
    </>
  );
}

function PreheatPaneFor({ monitor }: { monitor: Monitor }) {
  const engine = useStore((s) => s.engine);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const control = engine?.integrations.find((i) => i.id === printer?.provider)?.heater_control ?? false;
  if (!printer) return <p className="px-4 py-3 text-sm text-text-1">Bind a printer to this monitor to preheat it.</p>;
  if (!control) return <p className="px-4 py-3 text-sm text-text-1">{printer.name} doesn't let PrintGuard set its temperatures.</p>;
  if (!printer.device_state) return <p className="px-4 py-3 text-sm text-text-1">Waiting for {printer.name} to report its temperatures.</p>;
  return <PreheatPane printer={printer} />;
}

export function MonitorHero({ monitor }: { monitor: Monitor }) {
  const engine = useStore((s) => s.engine);
  const [pane, setPane] = useState<Pane>("control");
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const device = engine?.printers.find((p) => p.id === monitor.printer_id)?.device_state;
  const tools = usePluginSurface("monitor", monitor.id);
  const covered = useCovered();
  const prefix = "hero";
  return (
    <section aria-label={`${monitor.name}, selected monitor`} className="grid border-b border-rule lg:grid-cols-[minmax(0,1.32fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col border-rule max-lg:border-b lg:border-r">
        <Feed
          camera={camera}
          active={!covered}
          banner={monitor.alert && <span className="mono relative z-[4] bg-bad px-4 py-1.5 text-xs font-bold tracking-[0.2em] text-on-bad">DEFECT DETECTED</span>}
        >
          {activeJob(device) && <ProgressBar state={device} className="absolute inset-x-0 bottom-0 z-[3] h-1" />}
        </Feed>
        <div className="mono flex min-h-11 items-stretch border-t border-rule text-xs">
          <p className="flex min-w-0 flex-1 items-center justify-between gap-3 px-4 py-2">
            <span className="truncate">{camera ? `${camera.name} · ${sourceLabel(camera.source)}` : "No camera"}</span>
            {camera?.online && (
              <span className="whitespace-nowrap text-text-2">
                {monitor.watching ? `${camera.achieved_fps.toFixed(1)}/${camera.target_fps.toFixed(1)} fps · ` : ""}max {camera.max_fps.toFixed(0)}
              </span>
            )}
          </p>
          {tools.map(({ plugin, node }) => (
            <div key={plugin.id} className="flex items-center border-l border-rule px-2">
              <PluginNodeView plugin={plugin} node={node} />
            </div>
          ))}
        </div>
      </div>
      <div className="flex min-w-0 flex-col">
        <Tabs prefix={prefix} label="Monitor panes" tabs={PANES} value={pane} onChange={setPane} cells />
        <div className="grid flex-1">
          {PANES.map(({ id }) => (
            <TabPanel key={id} prefix={prefix} id={id} className={`flex flex-col [grid-area:1/1] ${pane === id ? "" : "invisible"}`}>
              {id === "control" && <ControlPane monitor={monitor} />}
              {id === "tune" && <TunePane monitor={monitor} />}
              {id === "preheat" && <PreheatPaneFor monitor={monitor} />}
            </TabPanel>
          ))}
        </div>
      </div>
    </section>
  );
}
