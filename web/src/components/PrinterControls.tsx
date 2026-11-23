import { useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useFocusKept } from "../a11y";
import { formatDuration } from "../prints";
import { useStore } from "../store";
import { useDraftCommit } from "../submit";
import type { DeviceState, Heater, PreheatPreset, Printer } from "../types";
import { ConfirmButton } from "./ConfirmButton";

export const HEATERS = ["nozzle", "bed"] as const;
export type HeaterName = (typeof HEATERS)[number];
export const HEATER_MAX: Record<HeaterName, number> = { nozzle: 350, bed: 150 };
const MAX_PRESETS = 12;

const clampTarget = (name: HeaterName, target: number) => Math.min(HEATER_MAX[name], Math.max(0, target));

export function activeJob(state: DeviceState | null | undefined): state is DeviceState {
  return state?.status === "printing" || state?.status === "paused";
}

export function heaterText(heater: Heater): string {
  const actual = `${Math.round(heater.actual)}°`;
  return heater.target > 0 ? `${actual} / ${Math.round(heater.target)}°` : actual;
}

export function jobText(state: DeviceState): string {
  return [state.job, state.remaining_s != null && `${formatDuration(state.remaining_s)} left`].filter(Boolean).join(" · ");
}

export function ProgressBar({ state, className = "" }: { state: DeviceState; className?: string }) {
  return (
    <div
      role="progressbar"
      aria-label="Print progress"
      aria-valuenow={Math.round(state.progress)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`overflow-hidden bg-line-0 ${className}`}
    >
      <div
        className={`h-full transition-[width] duration-700 ${state.status === "paused" ? "bg-warn" : "bg-accent"}`}
        style={{ width: `${Math.min(100, Math.max(0, state.progress))}%` }}
      />
    </div>
  );
}

export function HeaterReadouts({ state }: { state: DeviceState | null | undefined }) {
  return (
    <div className="grid grid-cols-2">
      {HEATERS.map((name, index) => {
        const heater = state?.[name];
        return (
          <div key={name} className={`px-4 py-3 ${index ? "border-l border-line-0" : ""}`}>
            <div className="label">{name}</div>
            <div className={`mono text-xl font-semibold tracking-[-0.03em] ${heater && heater.target > 0 ? "text-accent" : ""}`}>
              {heater ? `${Math.round(heater.actual)}°` : "-"}
            </div>
            <div className="mono text-xs text-text-2">{heater ? (heater.target > 0 ? `target ${Math.round(heater.target)}°` : "off") : "not reported"}</div>
          </div>
        );
      })}
    </div>
  );
}

export function PrintActions({ printer }: { printer: Printer }) {
  const { send, acting } = useStore(useShallow((s) => ({ send: s.send, acting: s.isPending("printer.action", printer.id) })));
  const [action, setAction] = useState<string | null>(null);
  const state = printer.device_state;
  const act = (name: "pause" | "resume" | "cancel") => {
    setAction(name);
    send({ cmd: "printer.action", id: printer.id, action: name });
  };
  const resume = state?.status === "paused";
  const primary = resume ? "resume" : "pause";
  return (
    <div className="grid grid-cols-[1.25fr_1fr]">
      <button className="cell-action cell-action-primary" disabled={acting || !activeJob(state)} onClick={() => act(primary)}>
        {acting && action === primary ? `${primary}…` : `${primary} print`}
      </button>
      <ConfirmButton className="cell-action" disabled={acting || !activeJob(state)} onConfirm={() => act("cancel")}>
        {acting && action === "cancel" ? "cancel…" : "cancel print"}
      </ConfirmButton>
    </div>
  );
}

function TargetField({ name, heater, busy, onCommit }: { name: HeaterName; heater: Heater; busy: boolean; onCommit: (target: number) => boolean }) {
  const current = String(Math.round(heater.target));
  const { draft, set, reset, commit } = useDraftCommit(
    () => current,
    [heater.target],
    (value) => {
      const target = clampTarget(name, Number(value));
      if (value.trim() === "" || Number.isNaN(target)) return reset(current);
      const sent = target === Math.round(heater.target) || onCommit(target);
      reset(String(sent ? target : Math.round(heater.target)));
    },
    busy,
  );
  return (
    <label className="flex items-center gap-1.5">
      <span className="sr-only">{name} target</span>
      <input
        className="field text-right"
        type="number"
        inputMode="numeric"
        min={0}
        max={HEATER_MAX[name]}
        disabled={busy}
        value={draft}
        onChange={(e) => set(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <span className="mono text-xs text-text-2">°C</span>
    </label>
  );
}

function PresetRow({ preset, onChange, onRemove }: { preset: PreheatPreset; onChange: (next: PreheatPreset) => void; onRemove: () => void }) {
  const typed = () => ({ name: preset.name, nozzle: String(preset.nozzle), bed: String(preset.bed) });
  const { draft, set, reset, commit } = useDraftCommit(typed, [preset.name, preset.nozzle, preset.bed], (value) => {
    const next = { name: value.name.trim(), nozzle: clampTarget("nozzle", Number(value.nozzle) || 0), bed: clampTarget("bed", Number(value.bed) || 0) };
    if (!next.name) return reset(typed());
    if (next.name !== preset.name || next.nozzle !== preset.nozzle || next.bed !== preset.bed) onChange(next);
    else reset(typed());
  });
  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && e.currentTarget.blur();
  return (
    <div className="flex items-center gap-2">
      <input
        className="field min-w-0 flex-1"
        aria-label="Preset name"
        value={draft.name}
        maxLength={20}
        onChange={(e) => set({ ...draft, name: e.target.value })}
        onBlur={commit}
        onKeyDown={blurOnEnter}
      />
      {HEATERS.map((name) => (
        <input
          key={name}
          className="field text-right"
          style={{ width: "4.5rem", flex: "none" }}
          aria-label={`${preset.name} ${name} target`}
          type="number"
          inputMode="numeric"
          min={0}
          max={HEATER_MAX[name]}
          value={draft[name]}
          onChange={(e) => set({ ...draft, [name]: e.target.value })}
          onBlur={commit}
          onKeyDown={blurOnEnter}
        />
      ))}
      <button
        className="btn btn-danger px-2"
        aria-label={`Remove ${preset.name}`}
        onClick={() => {
          reset(typed());
          onRemove();
        }}
      >
        ×
      </button>
    </div>
  );
}

function PresetEditor({ presets }: { presets: PreheatPreset[] }) {
  const updateSettings = useStore((s) => s.updateSettings);
  const rows = useFocusKept<HTMLDivElement>();
  const save = (next: PreheatPreset[]) => updateSettings({ preheat: next });
  return (
    <div ref={rows} className="space-y-2 px-4 py-3">
      <div className="flex items-center gap-2 pr-11">
        <span className="label flex-1">Name</span>
        {HEATERS.map((name) => (
          <span key={name} className="label text-right" style={{ width: "4.5rem" }}>
            {name} °C
          </span>
        ))}
      </div>
      {presets.map((preset, index) => (
        <PresetRow
          key={index}
          preset={preset}
          onChange={(next) => save(presets.map((p, i) => (i === index ? next : p)))}
          onRemove={() => save(presets.filter((_, i) => i !== index))}
        />
      ))}
      <button
        className="btn"
        disabled={presets.length >= MAX_PRESETS}
        onClick={() => save([...presets, { name: `Preset ${presets.length + 1}`, nozzle: 200, bed: 60 }])}
      >
        + Add preset
      </button>
    </div>
  );
}

export function PreheatPane({ printer }: { printer: Printer }) {
  const { savedPresets, send, heating } = useStore(
    useShallow((s) => ({
      savedPresets: s.engine?.settings.preheat,
      send: s.send,
      heating: s.isPending("printer.heat", printer.id),
    })),
  );
  const presets = savedPresets ?? [];
  const [editing, setEditing] = useState(false);
  const [committed, setCommitted] = useState<HeaterName[]>([]);
  const state = printer.device_state;
  const heat = (targets: Partial<Record<HeaterName, number>>) => send({ cmd: "printer.heat", id: printer.id, ...targets });
  const apply = (nozzle: number, bed: number) => heat({ nozzle: clampTarget("nozzle", nozzle), bed: clampTarget("bed", bed) });
  return (
    <>
      <div className="grid grid-cols-2 border-b border-line-0">
        {HEATERS.map((name, index) => {
          const heater = state?.[name];
          return (
            <div key={name} className={`grid gap-1.5 px-4 py-3 ${index ? "border-l border-line-0" : ""}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="label">{name}</span>
                <span className="mono text-base font-semibold">{heater ? `${Math.round(heater.actual)}°` : "-"}</span>
              </div>
              {heater && (
                <TargetField
                  name={name}
                  heater={heater}
                  busy={heating && committed.includes(name)}
                  onCommit={(target) => {
                    setCommitted(heating ? [...committed, name] : [name]);
                    return heat({ [name]: target }) !== null;
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between gap-2 border-b border-line-0 bg-ink-1 px-4 py-1.5">
        <span className="label">Preheat presets</span>
        <button className="btn-inline" aria-pressed={editing} onClick={() => setEditing((v) => !v)}>
          {editing ? "Done" : "Edit"}
        </button>
      </div>
      {editing ? (
        <PresetEditor presets={presets} />
      ) : (
        <div className="grid flex-1 auto-rows-fr grid-cols-2">
          {presets.map((preset, index) => (
            <button key={index} className="cell-option" disabled={heating} onClick={() => apply(preset.nozzle, preset.bed)}>
              <strong>{preset.name}</strong>
              <span className="mono text-xs text-text-2">
                {preset.nozzle}° / {preset.bed}°
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="grid border-t border-rule">
        <button className="cell-action" disabled={heating} onClick={() => apply(0, 0)}>
          Heaters off
        </button>
      </div>
    </>
  );
}
