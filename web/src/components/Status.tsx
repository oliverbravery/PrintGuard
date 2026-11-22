import type { DeviceState, Monitor } from "../types";

export type Tone = "ok" | "warn" | "bad" | "idle";

const GLYPHS: Record<Tone, string> = { ok: "●", warn: "■", bad: "▲", idle: "○" };
const COLOURS: Record<Tone, string> = { ok: "text-ok", warn: "text-warn", bad: "text-bad", idle: "text-text-2" };

export function Status({ tone, children, className = "" }: { tone: Tone; children: React.ReactNode; className?: string }) {
  return (
    <span className={`mono inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.04em] ${COLOURS[tone]} ${className}`}>
      <span aria-hidden className="text-xs">
        {GLYPHS[tone]}
      </span>
      {children}
    </span>
  );
}

export function deviceTone(state: DeviceState | null | undefined): Tone {
  if (state?.status === "printing") return "ok";
  if (state?.status === "paused") return "warn";
  if (state?.status === "error") return "bad";
  return "idle";
}

export function DeviceStatus({ state }: { state: DeviceState | null | undefined }) {
  if (!state) return null;
  return (
    <Status tone={deviceTone(state)}>
      {state.status}
      {state.status === "printing" && ` ${state.progress.toFixed(0)}%`}
    </Status>
  );
}

export function monitorState(monitor: Monitor, cameraOnline: boolean): { tone: Tone; text: string } {
  if (monitor.alert) return { tone: "bad", text: "defect" };
  if (!monitor.enabled) return { tone: "idle", text: "off" };
  if (!monitor.camera_id) return { tone: "idle", text: "no camera" };
  if (!monitor.watching) return { tone: "idle", text: "standby" };
  if (!cameraOnline) return { tone: "warn", text: "no signal" };
  return { tone: "ok", text: "watching" };
}
