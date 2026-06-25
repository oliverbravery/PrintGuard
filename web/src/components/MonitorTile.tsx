import { cardButton } from "../a11y";
import { section, toggleHidden, togglePinned } from "../layout";
import { useStore } from "../store";
import type { DeviceState, Monitor } from "../types";
import { Feed } from "./Feed";
import { RiskGauge } from "./RiskGauge";
import { SortableItem, type SortableHandle } from "./Sortable";

export function DeviceChip({ state }: { state: DeviceState | undefined }) {
  if (!state) return null;
  const cls =
    state.status === "printing" ? "chip-ok" : state.status === "error" ? "chip-bad" : state.status === "paused" ? "chip-warn" : "";
  return (
    <span className={`chip ${cls}`}>
      {state.status}
      {state.status === "printing" && ` ${state.progress.toFixed(0)}%`}
    </span>
  );
}

export function MonitorTile({ monitor, index }: { monitor: Monitor; index: number }) {
  const { engine, history, openDetail, customising, mutateLayout } = useStore();
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  const score = history[monitor.id]?.at(-1)?.score ?? 0;
  const alerting = Boolean(monitor.alert);
  const pinned = section(engine?.settings.layout, "monitors").pinned.includes(monitor.id);

  const content = (handle?: SortableHandle) => (
    <>
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
      <div className="flex items-center gap-2.5 px-4 py-2.5">
        {handle ? (
          <button
            className="btn !py-1 !px-2 cursor-grab touch-none"
            aria-label={`Drag ${monitor.name} to reorder`}
            {...handle.attributes}
            {...handle.listeners}
          >
            ⠿
          </button>
        ) : (
          <span
            aria-hidden
            className={`led ${alerting ? "led-bad" : camera?.inferring ? "led-infer" : monitor.watching && camera?.online ? "led-on" : "led-off"}`}
          />
        )}
        <h3 className="display text-base font-semibold tracking-[0.08em] truncate flex-1">{monitor.name}</h3>
        {handle ? (
          <>
            <button
              className={`btn !py-1 !px-2 !text-[0.6rem] ${pinned ? "!border-accent !text-accent" : ""}`}
              aria-pressed={pinned}
              aria-label={`${pinned ? "Pinned" : "Pin"} ${monitor.name}`}
              onClick={() => mutateLayout("monitors", (s) => togglePinned(s, monitor.id))}
            >
              {pinned ? "Pinned" : "Pin"}
            </button>
            <button
              className="btn !py-1 !px-2 !text-[0.6rem]"
              aria-label={`Hide ${monitor.name}`}
              onClick={() => mutateLayout("monitors", (s) => toggleHidden(s, monitor.id))}
            >
              Hide
            </button>
          </>
        ) : (
          <>
            <DeviceChip state={printer?.device_state ?? undefined} />
            {!monitor.watching && <span className="chip">standby</span>}
          </>
        )}
      </div>
      <Feed camera={camera} mode={engine?.mode ?? "local"} />
      {alerting && (
        <div className="absolute inset-x-0 top-[calc(50%-14px)] z-[4] flex justify-center">
          <span className="display bg-bad text-on-accent text-xs font-bold tracking-[0.3em] px-4 py-1.5">
            DEFECT DETECTED
          </span>
        </div>
      )}
      <div className="flex items-center gap-4 px-4 py-2.5">
        <RiskGauge score={score} threshold={monitor.threshold} size={56} />
        <div className="flex-1 grid grid-cols-2 gap-x-4 gap-y-1">
          <div>
            <div className="mono text-[0.8rem]">
              {camera ? `${camera.achieved_fps.toFixed(1)}/${camera.target_fps.toFixed(1)}` : "—"}
            </div>
            <div className="label">infer fps</div>
          </div>
          <div>
            <div className="mono text-[0.8rem]">{camera ? `${camera.max_fps.toFixed(0)} fps` : "—"}</div>
            <div className="label">camera max</div>
          </div>
        </div>
      </div>
    </>
  );

  if (!customising)
    return (
      <article
        {...cardButton(() => openDetail(monitor.id), `Open ${monitor.name} monitor details`)}
        className={`panel tile reveal relative cursor-pointer transition-colors hover:border-line-1 ${alerting ? "tile-alert" : ""}`}
        style={{ "--i": index } as React.CSSProperties}
      >
        {content()}
      </article>
    );

  return (
    <SortableItem id={monitor.id}>
      {(handle) => (
        <article
          ref={handle.setNodeRef}
          style={handle.style}
          className={`panel tile relative ${alerting ? "tile-alert" : ""} ${pinned ? "!border-accent" : ""} ${handle.isDragging ? "z-10 opacity-90 shadow-xl" : ""}`}
        >
          {content(handle)}
        </article>
      )}
    </SortableItem>
  );
}
