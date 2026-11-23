import { useState } from "react";
import { Link } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { sourceLabel } from "../cameras";
import { alertOutcome } from "../history";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { Feed, useCovered } from "./Feed";
import { MonitorSettings } from "./MonitorSettings";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { activeJob, HeaterReadouts, jobText, PreheatPane, PrintActions, ProgressBar } from "./PrinterControls";
import { ReviewList } from "./ReviewList";
import { RiskMeter } from "./RiskMeter";
import { SaveStatus } from "./SaveStatus";
import { Segmented } from "./Segmented";
import { Slider } from "./Slider";
import { Sparkline } from "./Sparkline";
import { DeviceStatus, monitorState, Status } from "./Status";
import { TabPanel, Tabs } from "./Tabs";

type Pane = "control" | "tune" | "preheat" | "configure" | "review";

const PANES: { id: Pane; label: string }[] = [
  { id: "control", label: "Control" },
  { id: "tune", label: "Tune" },
  { id: "preheat", label: "Preheat" },
  { id: "configure", label: "Configure" },
  { id: "review", label: "Review" },
];

const RESPONSES: { value: Monitor["on_defect"]; label: string }[] = [
  { value: "none", label: "Alert" },
  { value: "pause", label: "Pause" },
  { value: "cancel", label: "Cancel" },
];

function Block({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`border-b border-line-0 px-4 py-3 ${className}`}>{children}</div>;
}

function RiskBlock({ monitor }: { monitor: Monitor }) {
  const { online, historyPoints } = useStore(
    useShallow((s) => ({
      online: Boolean(s.engine?.cameras.find((c) => c.id === monitor.camera_id)?.online),
      historyPoints: s.history[monitor.id],
    })),
  );
  const points = historyPoints ?? [];
  const score = online && monitor.watching ? (points.at(-1)?.score ?? 0) : null;
  return (
    <Block className="border-t border-t-rule">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="label">Defect risk</span>
        <Link to={`/monitors/${monitor.id}/history`} className="btn-inline">
          History
        </Link>
      </div>
      <RiskMeter score={score} threshold={monitor.threshold} size="hero" />
      <div className="mt-2">
        <Sparkline points={points} threshold={monitor.threshold} />
      </div>
      {monitor.alert && (
        <p className="mono mt-2 text-xs text-bad">
          {[`defect at ${(monitor.alert.score * 100).toFixed(0)}%`, alertOutcome(monitor.alert.action)].filter(Boolean).join(", ")}
        </p>
      )}
    </Block>
  );
}

function ControlPane({ monitor }: { monitor: Monitor }) {
  const { camera, printer } = useStore(
    useShallow((s) => ({
      camera: s.engine?.cameras.find((c) => c.id === monitor.camera_id),
      printer: s.engine?.printers.find((p) => p.id === monitor.printer_id),
    })),
  );
  const device = printer?.device_state;
  const state = monitorState(monitor, Boolean(camera?.online));
  return (
    <>
      <Block>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Status tone={state.tone}>{state.text}</Status>
          <DeviceStatus state={device} />
        </span>
        <h2 className="mt-1 truncate text-xl font-bold tracking-[-0.02em]">{monitor.name}</h2>
        <p className="mono truncate text-xs text-text-1">
          {activeJob(device) ? jobText(device) : printer ? `${printer.name}, ${printer.device_state?.status ?? "no status yet"}` : "No printer, alerts only"}
        </p>
      </Block>
      {printer ? (
        <>
          <div className="border-b border-rule">
            <HeaterReadouts state={device} />
          </div>
          <div className="surface z-[1] @3xl:sticky @3xl:bottom-0">
            <PrintActions key={printer.id} printer={printer} />
          </div>
        </>
      ) : (
        <p className="surface z-[1] border-b border-rule px-4 py-3 text-sm text-text-1 @3xl:sticky @3xl:bottom-0">Link a printer to pause or cancel failing prints automatically.</p>
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
          hint="The risk score a frame needs to hit to count as a defect. Raise it to cut false alarms, or lower it to catch subtler failures."
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
          hint="How many flagged frames in a row it takes before PrintGuard acts. Raise it to ignore brief blips, or lower it to react faster."
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
          hint="How long to wait after acting before triggering again, so one failure doesn't spam repeat alerts."
          onChange={(v) => updateMonitor(monitor.id, { cooldown_s: v })}
        />
      </Block>
      <div className="px-4 py-2">
        <SaveStatus scope={`monitor:${monitor.id}`} />
      </div>
    </>
  );
}

function PreheatPaneFor({ monitor }: { monitor: Monitor }) {
  const engine = useStore((s) => s.engine);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const control = engine?.integrations.find((i) => i.id === printer?.provider)?.heater_control ?? false;
  if (!printer) return <p className="px-4 py-3 text-sm text-text-1">Link a printer to this monitor to preheat it.</p>;
  if (!control) return <p className="px-4 py-3 text-sm text-text-1">{printer.name} doesn't support setting temperatures from PrintGuard.</p>;
  if (!printer.device_state) return <p className="px-4 py-3 text-sm text-text-1">Waiting for {printer.name} to report its temperatures.</p>;
  return <PreheatPane key={printer.id} printer={printer} />;
}

export function MonitorHero({ monitor }: { monitor: Monitor }) {
  const engine = useStore((s) => s.engine);
  const [pane, setPane] = useState<Pane>("control");
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const device = engine?.printers.find((p) => p.id === monitor.printer_id)?.device_state;
  const tools = usePluginSurface("monitor", monitor.id);
  const covered = useCovered();
  const waiting = (engine?.reviews ?? []).filter((review) => review.monitor_id === monitor.id && review.status === "ready").length;
  const tabs = PANES.map((tab) => (tab.id === "review" && waiting ? { ...tab, badge: `${waiting} to review` } : tab));
  const prefix = "hero";
  return (
    <section aria-label={`${monitor.name}, selected monitor`} className="@container h-full">
      <div className="grid @3xl:h-full @3xl:grid-cols-[minmax(0,1.32fr)_minmax(23rem,1fr)] @3xl:grid-rows-[minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col border-rule @max-3xl:border-b @3xl:min-h-0 @3xl:overflow-y-auto @3xl:border-r">
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
          <RiskBlock monitor={monitor} />
        </div>
        <div className="flex min-w-0 flex-col">
          <Tabs prefix={prefix} label="Monitor panes" tabs={tabs} value={pane} onChange={setPane} cells />
          <div className="relative flex-1 @3xl:min-h-0 @3xl:scroll-pb-14 @3xl:overflow-y-auto">
            {PANES.map(({ id }) => (
              <TabPanel
                key={id}
                prefix={prefix}
                id={id}
                className={pane === id ? "" : "hidden"}
              >
                {pane === id && id === "control" && <ControlPane monitor={monitor} />}
                {pane === id && id === "tune" && <TunePane monitor={monitor} />}
                {pane === id && id === "preheat" && <PreheatPaneFor monitor={monitor} />}
                {pane === id && id === "configure" && <MonitorSettings key={monitor.id} monitor={monitor} />}
                {pane === id && id === "review" && <ReviewList monitorId={monitor.id} />}
              </TabPanel>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
