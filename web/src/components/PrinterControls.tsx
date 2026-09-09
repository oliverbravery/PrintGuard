import { useEffect, useState } from "react";
import { formatDuration } from "../prints";
import { useStore } from "../store";
import type { DeviceState, Heater, PreheatPreset, Printer } from "../types";

export const HEATERS = ["nozzle", "bed"] as const;
type HeaterName = (typeof HEATERS)[number];
const HEATER_MAX: Record<HeaterName, number> = { nozzle: 350, bed: 150 };

export function activeJob(state: DeviceState | null | undefined): state is DeviceState {
  return state?.status === "printing" || state?.status === "paused";
}

export function heaterText(heater: Heater): string {
  const actual = `${Math.round(heater.actual)}°`;
  return heater.target > 0 ? `${actual} / ${Math.round(heater.target)}°` : actual;
}

export function ProgressBar({ state, className = "" }: { state: DeviceState; className?: string }) {
  return (
    <div
      role="progressbar"
      aria-label="Print progress"
      aria-valuenow={Math.round(state.progress)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={`overflow-hidden bg-text-2/25 ${className}`}
    >
      <div
        className={`h-full transition-[width] duration-700 ${state.status === "paused" ? "bg-warn" : "bg-accent"}`}
        style={{ width: `${Math.min(100, Math.max(0, state.progress))}%` }}
      />
    </div>
  );
}

function TargetField({ name, heater, busy, onCommit }: { name: HeaterName; heater: Heater; busy: boolean; onCommit: (target: number) => void }) {
  const [draft, setDraft] = useState(String(Math.round(heater.target)));
  useEffect(() => setDraft(String(Math.round(heater.target))), [heater.target]);
  const commit = () => {
    const target = Math.min(HEATER_MAX[name], Math.max(0, Number(draft)));
    if (draft.trim() === "" || Number.isNaN(target)) return setDraft(String(Math.round(heater.target)));
    setDraft(String(target));
    if (target !== Math.round(heater.target)) onCommit(target);
  };
  return (
    <label className="flex items-center gap-1.5">
      <span className="sr-only">{name} target</span>
      <input
        className="field !w-16 text-right"
        type="number"
        inputMode="numeric"
        min={0}
        max={HEATER_MAX[name]}
        disabled={busy}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <span className="mono text-[0.7rem] text-text-2">°C</span>
    </label>
  );
}

function HeaterCard({ name, heater, control, busy, onTarget }: { name: HeaterName; heater: Heater; control: boolean; busy: boolean; onTarget: (target: number) => void }) {
  const heating = heater.target > 0;
  return (
    <div className="panel flex items-center gap-3 px-3 py-2">
      <div className="min-w-0 flex-1 leading-tight">
        <div className="label">{name}</div>
        <div className={`mono text-base ${heating ? "text-accent" : "text-text-0"}`}>{heater.actual.toFixed(1)}°</div>
      </div>
      {control ? (
        <TargetField name={name} heater={heater} busy={busy} onCommit={onTarget} />
      ) : (
        <span className="mono text-[0.7rem] text-text-2">{heating ? `→ ${Math.round(heater.target)}°` : "off"}</span>
      )}
    </div>
  );
}

function PresetRow({ preset, onChange, onRemove }: { preset: PreheatPreset; onChange: (next: PreheatPreset) => void; onRemove: () => void }) {
  const [draft, setDraft] = useState(preset);
  useEffect(() => setDraft(preset), [preset.name, preset.nozzle, preset.bed]);
  const commit = () => {
    const next = { ...draft, name: draft.name.trim(), nozzle: Number(draft.nozzle) || 0, bed: Number(draft.bed) || 0 };
    if (!next.name) return setDraft(preset);
    if (next.name !== preset.name || next.nozzle !== preset.nozzle || next.bed !== preset.bed) onChange(next);
  };
  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && e.currentTarget.blur();
  return (
    <div className="flex items-center gap-2">
      <input
        className="field min-w-0 flex-1"
        aria-label="Preset name"
        value={draft.name}
        maxLength={20}
        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        onBlur={commit}
        onKeyDown={blurOnEnter}
      />
      {HEATERS.map((name) => (
        <input
          key={name}
          className="field !w-16 text-right"
          aria-label={`${preset.name} ${name} target`}
          type="number"
          inputMode="numeric"
          min={0}
          max={HEATER_MAX[name]}
          value={draft[name]}
          onChange={(e) => setDraft({ ...draft, [name]: e.target.value === "" ? 0 : Number(e.target.value) })}
          onBlur={commit}
          onKeyDown={blurOnEnter}
        />
      ))}
      <button className="btn btn-danger !px-2 !py-1" aria-label={`Remove ${preset.name}`} onClick={onRemove}>
        ×
      </button>
    </div>
  );
}

function Presets({ presets, busy, onApply }: { presets: PreheatPreset[]; busy: boolean; onApply: (nozzle: number, bed: number) => void }) {
  const updateSettings = useStore((s) => s.updateSettings);
  const [editing, setEditing] = useState(false);
  const save = (next: PreheatPreset[]) => updateSettings({ preheat: next });
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="label">Preheat</span>
        <div className="hairline flex-1" />
        <button className="btn !px-2 !py-0.5 !text-[0.6rem]" aria-pressed={editing} onClick={() => setEditing((v) => !v)}>
          {editing ? "Done" : "Edit"}
        </button>
      </div>
      {editing ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2 pr-9">
            <span className="label flex-1">Name</span>
            {HEATERS.map((name) => (
              <span key={name} className="label w-16 text-right">
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
            className="btn !px-2.5 !py-1 !text-[0.62rem]"
            disabled={presets.length >= 12}
            onClick={() => save([...presets, { name: `Preset ${presets.length + 1}`, nozzle: 200, bed: 60 }])}
          >
            + Add preset
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {presets.map((preset, index) => (
            <button
              key={index}
              className="chip cursor-pointer hover:opacity-80 disabled:opacity-40"
              disabled={busy}
              title={`Nozzle ${preset.nozzle}°, bed ${preset.bed}°`}
              onClick={() => onApply(preset.nozzle, preset.bed)}
            >
              {preset.name} <span className="text-text-2">{preset.nozzle}/{preset.bed}</span>
            </button>
          ))}
          <button className="chip cursor-pointer hover:opacity-80 disabled:opacity-40" disabled={busy} title="Turn every heater off" onClick={() => onApply(0, 0)}>
            Off
          </button>
        </div>
      )}
    </div>
  );
}

export function PrinterControls({ printer }: { printer: Printer }) {
  const { engine, send, isPending } = useStore();
  const [action, setAction] = useState<string | null>(null);
  const state = printer.device_state;
  const control = engine?.integrations.find((i) => i.id === printer.provider)?.heater_control ?? false;
  const presets = engine?.settings.preheat ?? [];
  const acting = isPending("printer.action");
  const heating = isPending("printer.heat");
  const heat = (targets: Partial<Record<HeaterName, number>>) => send({ cmd: "printer.heat", id: printer.id, ...targets });
  const heaters = HEATERS.filter((name) => state?.[name]);

  return (
    <div className="space-y-4">
      {activeJob(state) && (
        <div>
          <div className="flex items-center gap-3">
            <ProgressBar state={state} className="h-1.5 flex-1 rounded-full" />
            <span className="mono text-[0.75rem] text-text-0">{Math.round(state.progress)}%</span>
          </div>
          <p className="mono mt-1.5 truncate text-[0.68rem] text-text-2">
            {[state.job, state.remaining_s != null && `${formatDuration(state.remaining_s)} left`].filter(Boolean).join(" · ")}
          </p>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        {(["pause", "resume", "cancel"] as const).map((name) => (
          <button
            key={name}
            className={`btn ${name === "cancel" ? "btn-danger" : ""}`}
            disabled={acting}
            onClick={() => {
              setAction(name);
              send({ cmd: "printer.action", id: printer.id, action: name });
            }}
          >
            {acting && action === name ? `${name}…` : name}
          </button>
        ))}
      </div>
      {heaters.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {heaters.map((name) => (
            <HeaterCard key={name} name={name} heater={state![name]!} control={control} busy={heating} onTarget={(target) => heat({ [name]: target })} />
          ))}
        </div>
      )}
      {control && state && <Presets presets={presets} busy={heating} onApply={(nozzle, bed) => heat({ nozzle, bed })} />}
    </div>
  );
}
