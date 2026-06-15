import { useStore } from "../store";
import type { DeviceState, Printer } from "../types";
import { Feed } from "./Feed";
import { RiskGauge } from "./RiskGauge";

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

export function PrinterTile({ printer, index }: { printer: Printer; index: number }) {
  const { engine, history, openDetail } = useStore();
  const camera = engine?.cameras.find((c) => c.id === printer.camera_id);
  const score = history[printer.id]?.at(-1)?.score ?? 0;
  const alerting = Boolean(printer.alert);
  return (
    <article
      className={`panel tile reveal relative cursor-pointer transition-colors hover:border-line-1 ${alerting ? "tile-alert" : ""}`}
      style={{ "--i": index } as React.CSSProperties}
      onClick={() => openDetail(printer.id)}
    >
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
      <div className="flex items-center gap-2.5 px-4 py-2.5">
        <span
          className={`led ${alerting ? "led-bad" : camera?.inferring ? "led-infer" : printer.watching && camera?.online ? "led-on" : "led-off"}`}
        />
        <h3 className="display text-base font-semibold tracking-[0.08em] truncate flex-1">{printer.name}</h3>
        <DeviceChip state={printer.device_state} />
        {!printer.watching && <span className="chip">standby</span>}
      </div>
      <Feed camera={camera} mode={engine?.mode ?? "local"} />
      {alerting && (
        <div className="absolute inset-x-0 top-[calc(50%-14px)] z-[4] flex justify-center">
          <span className="display bg-bad text-ink-0 text-xs font-bold tracking-[0.3em] px-4 py-1.5">
            DEFECT DETECTED
          </span>
        </div>
      )}
      <div className="flex items-center gap-4 px-4 py-2.5">
        <RiskGauge score={score} threshold={printer.threshold} size={56} />
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
    </article>
  );
}
