import type { Camera, EngineState, Monitor, PrintFile } from "./types";

export type OptimisticKind = "camera" | "monitor" | "print" | "settings";

export interface OptimisticEntry {
  kind: OptimisticKind;
  id?: string;
  patch: Record<string, unknown>;
  unsent: Record<string, unknown>;
  sent: Record<string, string>;
}

export function withoutKeys<T>(record: Record<string, T>, keys: string[]): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([key]) => !keys.includes(key)));
}

export function settle(overlay: Record<string, OptimisticEntry>, reqId: string): Record<string, OptimisticEntry> {
  const settled: Record<string, OptimisticEntry> = {};
  for (const [key, entry] of Object.entries(overlay)) {
    const answered = Object.keys(entry.sent).filter((field) => entry.sent[field] === reqId);
    if (!answered.length) settled[key] = entry;
    else if (Object.keys(entry.patch).some((field) => !answered.includes(field)))
      settled[key] = { ...entry, patch: withoutKeys(entry.patch, answered), sent: withoutKeys(entry.sent, answered) };
  }
  return settled;
}

export function applyOptimistic(engine: EngineState, overlay: Record<string, OptimisticEntry>): EngineState {
  let cameras = engine.cameras;
  let monitors = engine.monitors;
  let prints = engine.prints;
  let settings = engine.settings;
  for (const entry of Object.values(overlay)) {
    if (entry.kind === "camera") cameras = cameras.map((c) => (c.id === entry.id ? ({ ...c, ...entry.patch } as Camera) : c));
    else if (entry.kind === "monitor") monitors = monitors.map((m) => (m.id === entry.id ? ({ ...m, ...entry.patch } as Monitor) : m));
    else if (entry.kind === "print") prints = prints.map((p) => (p.id === entry.id ? ({ ...p, ...entry.patch } as PrintFile) : p));
    else settings = { ...settings, ...entry.patch } as EngineState["settings"];
  }
  return { ...engine, cameras, monitors, prints, settings };
}

export function commandFor(entry: OptimisticEntry): Record<string, unknown> {
  if (entry.kind === "settings") return { cmd: "settings.update", patch: entry.patch };
  return { cmd: `${entry.kind}.update`, id: entry.id, patch: entry.patch };
}
