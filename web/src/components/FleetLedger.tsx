import { ChevronDown, ChevronUp, Pencil } from "lucide-react";
import { createContext, useContext } from "react";
import { useParentPanel } from "react-resizable-panels";
import { Link } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { section, toggleHidden, type Tile } from "../layout";
import { awaitingReview, framesLabel } from "../review";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { Feed, useCovered } from "./Feed";
import { LayoutControls, useReorder } from "./LayoutControls";
import { AddCell } from "./Page";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { activeJob, HEATERS, heaterText, ProgressBar } from "./PrinterControls";
import { riskColor, RiskMeter } from "./RiskMeter";
import { Sortable, SortableItem, type SortableHandle, verticalListSortingStrategy } from "./Sortable";
import { DeviceStatus, monitorState, Status } from "./Status";

function counted(count: number, noun: string): string {
  return count ? `${count} ${noun}${count === 1 ? "" : "s"}` : "";
}

const COLUMNS = "grid-cols-[6.5rem_minmax(6rem,1fr)_auto] @3xl:grid-cols-[8rem_minmax(0,1.3fr)_minmax(0,0.7fr)_minmax(0,0.8fr)_minmax(0,1fr)]";

export function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`flex min-w-0 flex-col justify-center gap-1 border-l border-line-0 px-3 py-2 ${className}`}>{children}</div>;
}

function Row({ monitor, selected, handle, visible, group }: { monitor: Monitor; selected: boolean; handle?: SortableHandle; visible: string[]; group: string[] }) {
  const { camera, printer, awaiting, latestScore } = useStore(
    useShallow((s) => ({
      camera: s.engine?.cameras.find((c) => c.id === monitor.camera_id),
      printer: s.engine?.printers.find((p) => p.id === monitor.printer_id),
      awaiting: awaitingReview(s.engine?.reviews ?? [], monitor.id),
      latestScore: s.history[monitor.id]?.at(-1)?.score ?? 0,
    })),
  );
  const device = printer?.device_state;
  const tools = usePluginSurface("monitor", monitor.id);
  const score = camera?.online && monitor.watching ? latestScore : null;
  const state = monitorState(monitor, Boolean(camera?.online));
  const covered = useCovered();
  return (
    <li
      ref={handle?.setNodeRef}
      style={handle?.style}
      className={`relative grid border-b border-line-0 ${COLUMNS} ${selected ? "bg-ink-3 shadow-[inset_3px_0_0_var(--color-accent)]" : "hover:bg-ink-1"} ${
        handle?.isDragging ? "z-10 bg-ink-1" : ""
      }`}
    >
      <div className="p-2">
        <Feed camera={camera} compact active={!covered} />
      </div>
      <Cell>
        <Link
          to={`/monitors/${monitor.id}`}
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
        <span>{HEATERS.flatMap((name) => (device?.[name] ? [heaterText(device[name])] : [])).join(" · ") || "-"}</span>
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
            <span className="flex flex-wrap justify-end gap-x-3">
              <Status tone={state.tone}>{state.text}</Status>
              <DeviceStatus state={device} />
              {score !== null && (
                <span className="mono min-w-[9ch] text-right text-xs font-semibold @3xl:hidden" style={{ color: riskColor(score, monitor.threshold) }}>
                  risk {Math.round(score * 100)}%
                </span>
              )}
            </span>
            <div className="relative z-[1] flex flex-wrap justify-end gap-1">
              {awaiting && (
                <Link to={`/monitors/${monitor.id}/review/${awaiting.id}`} className="btn-inline btn-inline-accent" aria-label={`Review ${framesLabel(awaiting.frames)} from ${monitor.name}`}>
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

const FoldContext = createContext<{ folded: boolean; toggle: () => void } | null>(null);
export const FleetFold = FoldContext.Provider;

function FoldButton() {
  const fold = useContext(FoldContext);
  if (!fold) return null;
  const Icon = fold.folded ? ChevronUp : ChevronDown;
  return (
    <button
      className="cell-action grid min-w-11 place-items-center self-stretch px-3"
      aria-expanded={!fold.folded}
      aria-label={fold.folded ? "Show the fleet" : "Hide the fleet"}
      title={fold.folded ? "Show the fleet" : "Hide the fleet"}
      onClick={fold.toggle}
    >
      <Icon size={16} aria-hidden />
    </button>
  );
}

function HeightButtons() {
  const panel = useParentPanel();
  if (!panel) return null;
  const grow = (by: number) => panel.resize(`${Math.min(100, Math.max(0, panel.getSize().asPercentage + by))}%`);
  return (
    <>
      <button className="btn-inline" onClick={() => grow(10)}>
        Taller
      </button>
      <button className="btn-inline" onClick={() => grow(-10)}>
        Shorter
      </button>
    </>
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
  const { layout, customising, setCustomising, resetLayout, openDialog } = useStore(
    useShallow((s) => ({
      layout: s.engine?.settings.layout,
      customising: s.customising,
      setCustomising: s.setCustomising,
      resetLayout: s.resetLayout,
      openDialog: s.openDialog,
    })),
  );
  const fold = useContext(FoldContext);
  const pinned = section(layout).pinned;
  const group = monitors.map((m) => m.id);
  const reorder = useReorder(visible);
  const toggleLayout = () => {
    if (!customising && fold?.folded) fold.toggle();
    setCustomising(!customising);
  };
  return (
    <section aria-labelledby="fleet-heading" className="@container border-b border-rule">
      <div className="surface sticky top-0 z-[5]">
        <div className="flex min-h-11 items-center gap-2 border-b border-rule bg-ink-1 pl-4">
          <h2 id="fleet-heading" className="label flex-1 text-text-1">
            Fleet · {monitors.length}
          </h2>
          {customising && (
            <>
              <HeightButtons />
              <ConfirmButton className="btn-inline" onConfirm={resetLayout}>
                Reset layout
              </ConfirmButton>
            </>
          )}
          {!customising && <AddCell label="Add monitor" onClick={() => openDialog("monitor")} />}
          <button className="cell-action flex items-center gap-2 self-stretch px-4 text-xs" aria-pressed={customising} onClick={toggleLayout}>
            {customising ? "Done" : "Layout"}
            {!customising && <Pencil size={13} aria-hidden />}
          </button>
          <FoldButton />
        </div>
        <div aria-hidden className={`label grid border-b border-line-0 @max-3xl:hidden ${COLUMNS}`}>
          {["Frame", "Monitor / job", "Heaters", "Risk", "State and tools"].map((heading, index) => (
            <span key={heading} className={`px-3 py-1.5 ${index ? "border-l border-line-0" : ""} ${index === 4 ? "text-right" : ""}`}>
              {heading}
            </span>
          ))}
        </div>
      </div>
      {customising && <p className="border-b border-line-0 px-4 py-2 text-sm text-text-2">Drag a row or use its arrows to reorder. Pinned rows stay at the top.</p>}
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
