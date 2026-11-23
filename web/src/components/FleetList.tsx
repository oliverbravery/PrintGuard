import { Pencil } from "lucide-react";
import { Link } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { section, toggleHidden, type Tile } from "../layout";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { Feed, useCovered } from "./Feed";
import { LayoutRow, useReorder } from "./LayoutControls";
import { AddCell, ListHead } from "./Page";
import { activeJob, ProgressBar } from "./PrinterControls";
import { riskColor } from "./RiskMeter";
import { Sortable, SortableItem, type SortableHandle, verticalListSortingStrategy } from "./Sortable";
import { DeviceStatus, monitorState, Status } from "./Status";

function counted(count: number, noun: string): string {
  return count ? `${count} ${noun}${count === 1 ? "" : "s"}` : "";
}

function MonitorRow({ monitor, selected, handle, visible, group }: { monitor: Monitor; selected: boolean; handle?: SortableHandle; visible: string[]; group: string[] }) {
  const { camera, printer, latestScore } = useStore(
    useShallow((s) => ({
      camera: s.engine?.cameras.find((c) => c.id === monitor.camera_id),
      printer: s.engine?.printers.find((p) => p.id === monitor.printer_id),
      latestScore: s.history[monitor.id]?.at(-1)?.score ?? 0,
    })),
  );
  const device = printer?.device_state;
  const score = camera?.online && monitor.watching ? latestScore : null;
  const state = monitorState(monitor, Boolean(camera?.online));
  const covered = useCovered();
  return (
    <LayoutRow
      id={monitor.id}
      name={monitor.name}
      handle={handle}
      visible={visible}
      group={group}
      thumb={<Feed camera={camera} compact active={!covered} className="w-20 shrink-0" />}
      trailing={
        score !== null && (
          <span className="mono text-xs font-semibold" style={{ color: riskColor(score, monitor.threshold) }}>
            <span className="sr-only">risk </span>
            {Math.round(score * 100)}%
          </span>
        )
      }
    >
      <Link to={`/monitors/${monitor.id}`} aria-current={selected ? "page" : undefined} className="truncate text-sm font-semibold after:absolute after:inset-0 after:content-['']">
        {monitor.name}
      </Link>
      <span className="flex flex-wrap gap-x-3 whitespace-nowrap">
        <Status tone={state.tone}>{state.text}</Status>
        <DeviceStatus state={device} />
      </span>
      <span className="mono truncate text-xs text-text-2">{activeJob(device) ? (device.job ?? "printing") : printer ? printer.name : "alerts only"}</span>
      {activeJob(device) && <ProgressBar state={device} className="mt-1 h-0.5" />}
    </LayoutRow>
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

export function FleetList({ monitors, selectedId, visible, hidden }: { monitors: Monitor[]; selectedId: string | null; visible: string[]; hidden: Tile[] }) {
  const { layout, customising, setCustomising, resetLayout, openDialog } = useStore(
    useShallow((s) => ({
      layout: s.engine?.settings.layout,
      customising: s.customising,
      setCustomising: s.setCustomising,
      resetLayout: s.resetLayout,
      openDialog: s.openDialog,
    })),
  );
  const pinned = section(layout).pinned;
  const group = monitors.map((m) => m.id);
  const reorder = useReorder(visible);
  return (
    <section aria-label="Fleet">
      <div className="surface sticky top-0 z-[5]">
        <ListHead
          title={`Fleet · ${monitors.length}`}
          action={
            <>
              {!customising && <AddCell label="Add monitor" onClick={() => openDialog("monitor")} />}
              <button
                className="cell-action flex min-w-11 items-center justify-center self-stretch px-4 text-xs"
                aria-pressed={customising}
                aria-label={customising ? undefined : "Layout"}
                title={customising ? undefined : "Layout"}
                onClick={() => setCustomising(!customising)}
              >
                {customising ? "Done" : <Pencil size={14} aria-hidden />}
              </button>
            </>
          }
        />
      </div>
      {customising && (
        <div className="space-y-2 border-b border-line-0 px-4 py-3">
          <p className="text-sm text-text-2">Drag a row or use its arrows to reorder. Pinned rows stay at the top.</p>
          <ConfirmButton className="btn-inline" onConfirm={resetLayout}>
            Reset layout
          </ConfirmButton>
        </div>
      )}
      {customising && <HiddenTray hidden={hidden} />}
      {monitors.length === 0 && !customising && hidden.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 px-4 py-3">
          <p className="text-sm text-text-1">
            {[counted(hidden.filter((tile) => tile.monitor).length, "monitor"), counted(hidden.filter((tile) => tile.plugin).length, "plugin panel")]
              .filter(Boolean)
              .join(" and ")}{" "}
            hidden
          </p>
          <button className="btn-inline" onClick={() => setCustomising(true)}>
            Layout
          </button>
        </div>
      )}
      <Sortable ids={group} pinned={pinned} strategy={verticalListSortingStrategy} disabled={!customising} onReorder={reorder}>
        <ul>
          {monitors.map((monitor) =>
            customising ? (
              <SortableItem key={monitor.id} id={monitor.id}>
                {(handle) => <MonitorRow monitor={monitor} selected={monitor.id === selectedId} handle={handle} visible={visible} group={group} />}
              </SortableItem>
            ) : (
              <MonitorRow key={monitor.id} monitor={monitor} selected={monitor.id === selectedId} visible={visible} group={group} />
            ),
          )}
        </ul>
      </Sortable>
    </section>
  );
}
