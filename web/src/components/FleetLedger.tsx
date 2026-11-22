import { Link } from "react-router";
import { section, toggleHidden, type Tile } from "../layout";
import { awaitingReview } from "../review";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { Feed } from "./Feed";
import { LayoutControls, useReorder } from "./LayoutControls";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { activeJob, heaterText, ProgressBar } from "./PrinterControls";
import { RiskMeter } from "./RiskMeter";
import { Sortable, SortableItem, type SortableHandle, verticalListSortingStrategy } from "./Sortable";
import { DeviceStatus, monitorState, Status } from "./Status";

const COLUMNS = "grid-cols-[6.5rem_minmax(0,1fr)_auto] @3xl:grid-cols-[8rem_minmax(0,1.3fr)_minmax(0,0.7fr)_minmax(0,0.8fr)_minmax(0,1fr)]";

function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`flex min-w-0 flex-col justify-center gap-1 border-l border-line-0 px-3 py-2 ${className}`}>{children}</div>;
}

function Row({ monitor, selected, handle, visible, group }: { monitor: Monitor; selected: boolean; handle?: SortableHandle; visible: string[]; group: string[] }) {
  const { engine, history } = useStore();
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const device = printer?.device_state;
  const awaiting = awaitingReview(engine?.reviews ?? [], monitor.id);
  const tools = usePluginSurface("monitor", monitor.id);
  const score = camera?.online && monitor.watching ? (history[monitor.id]?.at(-1)?.score ?? 0) : null;
  const state = monitorState(monitor, Boolean(camera?.online));
  return (
    <li
      ref={handle?.setNodeRef}
      style={handle?.style}
      className={`relative grid border-b border-line-0 ${COLUMNS} ${selected ? "bg-ink-3 shadow-[inset_3px_0_0_var(--color-accent)]" : "hover:bg-ink-1"} ${
        handle?.isDragging ? "z-10 bg-ink-1" : ""
      }`}
    >
      <div className="p-2" aria-hidden>
        <Feed camera={camera} compact />
      </div>
      <Cell>
        <Link
          to={`/monitors/${monitor.id}`}
          replace
          aria-current={selected ? "true" : undefined}
          className="truncate font-bold after:absolute after:inset-0 after:content-['']"
        >
          {monitor.name}
        </Link>
        <p className="mono truncate text-xs text-text-2">
          {activeJob(device) ? `${device.job ?? "printing"} · ${Math.round(device.progress)}%` : printer ? printer.name : "alerts only"}
        </p>
        {activeJob(device) && <ProgressBar state={device} className="h-0.5" />}
      </Cell>
      <Cell className="mono text-sm @max-3xl:hidden">
        <span>{device?.nozzle && device.bed ? `${heaterText(device.nozzle)} · ${heaterText(device.bed)}` : "-"}</span>
        <span className="text-xs text-text-2">{camera?.online && monitor.watching ? `${camera.achieved_fps.toFixed(1)} fps` : state.text}</span>
      </Cell>
      <Cell className="@max-3xl:hidden">
        <RiskMeter score={score} threshold={monitor.threshold} />
      </Cell>
      <Cell className="items-end">
        {handle ? (
          <LayoutControls id={monitor.id} name={monitor.name} handle={handle} visible={visible} group={group} />
        ) : (
          <>
            {monitor.alert || !printer ? <Status tone={state.tone}>{state.text}</Status> : <DeviceStatus state={device} />}
            <div className="relative z-[1] flex flex-wrap justify-end gap-1">
              {awaiting && (
                <Link to={`/monitors/${monitor.id}/review/${awaiting.id}`} className="btn-inline btn-inline-accent" aria-label={`Review ${awaiting.frames} frames from ${monitor.name}`}>
                  Review {awaiting.frames}
                </Link>
              )}
              <Link to={`/monitors/${monitor.id}/history`} className="btn-inline" aria-label={`${monitor.name} history`}>
                History
              </Link>
              {tools.map(({ plugin, node }) => (
                <PluginNodeView key={plugin.id} plugin={plugin} node={node} />
              ))}
            </div>
          </>
        )}
      </Cell>
    </li>
  );
}

function HiddenTray({ hidden }: { hidden: Tile[] }) {
  const mutateLayout = useStore((s) => s.mutateLayout);
  if (hidden.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line-0 px-4 py-3">
      <span className="label mr-2">Hidden</span>
      {hidden.map((tile) => (
        <button key={tile.id} className="btn-inline" onClick={() => mutateLayout((s) => toggleHidden(s, tile.id))}>
          {tile.name} · show
        </button>
      ))}
    </div>
  );
}

export function FleetLedger({ monitors, selectedId, visible, hidden }: { monitors: Monitor[]; selectedId: string | null; visible: string[]; hidden: Tile[] }) {
  const { engine, customising, setCustomising, resetLayout } = useStore();
  const pinned = section(engine?.settings.layout).pinned;
  const group = monitors.map((m) => m.id);
  const reorder = useReorder(visible);
  return (
    <section aria-labelledby="fleet-heading" className="@container border-b border-rule">
      <div className="flex min-h-11 items-center gap-2 border-b border-rule bg-ink-1 pl-4">
        <h2 id="fleet-heading" className="label flex-1 text-text-1">
          Fleet · {monitors.length}
        </h2>
        {customising && (
          <ConfirmButton className="btn-inline" onConfirm={resetLayout}>
            Reset layout
          </ConfirmButton>
        )}
        <button className="cell-action self-stretch px-4 text-xs" aria-pressed={customising} onClick={() => setCustomising(!customising)}>
          {customising ? "Done" : "Layout"}
        </button>
      </div>
      <div aria-hidden className={`label grid border-b border-line-0 @max-3xl:hidden ${COLUMNS}`}>
        {["Frame", "Monitor / job", "Heaters", "Risk", "State and tools"].map((heading, index) => (
          <span key={heading} className={`px-3 py-1.5 ${index ? "border-l border-line-0" : ""} ${index === 4 ? "text-right" : ""}`}>
            {heading}
          </span>
        ))}
      </div>
      {customising && <HiddenTray hidden={hidden} />}
      {monitors.length === 0 && !customising && hidden.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <p className="text-sm text-text-1">Every monitor is hidden.</p>
          <button className="btn-inline" onClick={() => setCustomising(true)}>
            Show them
          </button>
        </div>
      )}
      <Sortable ids={group} pinned={pinned} strategy={verticalListSortingStrategy} disabled={!customising} onReorder={reorder}>
        <ul>
          {monitors.map((monitor) =>
            customising ? (
              <SortableItem key={monitor.id} id={monitor.id}>
                {(handle) => <Row monitor={monitor} selected={monitor.id === selectedId} handle={handle} visible={visible} group={group} />}
              </SortableItem>
            ) : (
              <Row key={monitor.id} monitor={monitor} selected={monitor.id === selectedId} visible={visible} group={group} />
            ),
          )}
        </ul>
      </Sortable>
    </section>
  );
}
