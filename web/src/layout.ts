import type { EngineState, Layout, LayoutSection, Monitor, PluginRecord } from "./types";

const EMPTY: LayoutSection = { order: [], pinned: [], hidden: [] };

export function section(layout: Layout | undefined): LayoutSection {
  return { ...EMPTY, ...(layout?.monitors ?? {}) };
}

export interface Tile {
  id: string;
  name: string;
  monitor?: Monitor;
  plugin?: PluginRecord;
}

export function tiles(engine: EngineState | null | undefined): Tile[] {
  const panels = (engine?.plugins ?? []).filter(
    (p) => p.enabled && p.manifest.surfaces.includes("panel") && (p.files.includes("plugin.js") || p.files.includes("panel.html")),
  );
  return [
    ...(engine?.monitors ?? []).map((monitor) => ({ id: monitor.id, name: monitor.name, monitor })),
    ...panels.map((plugin) => ({ id: plugin.id, name: plugin.manifest.name, plugin })),
  ];
}

export function applyLayout<T extends { id: string }>(
  items: T[],
  sec: LayoutSection,
): { visible: T[]; hidden: T[] } {
  const rank = new Map(sec.order.map((id, i) => [id, i] as const));
  const pinned = new Set(sec.pinned);
  const hidden = new Set(sec.hidden);
  const score = (item: T) => rank.get(item.id) ?? sec.order.length + items.indexOf(item);
  const visible = items
    .filter((item) => !hidden.has(item.id))
    .sort((a, b) => Number(pinned.has(b.id)) - Number(pinned.has(a.id)) || score(a) - score(b));
  return { visible, hidden: items.filter((item) => hidden.has(item.id)) };
}

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export function sharesPinning(pinned: string[], a: string, b: string): boolean {
  return pinned.includes(a) === pinned.includes(b);
}

export function togglePinned(sec: LayoutSection, id: string): LayoutSection {
  return { ...sec, pinned: toggle(sec.pinned, id) };
}

export function toggleHidden(sec: LayoutSection, id: string): LayoutSection {
  return { ...sec, hidden: toggle(sec.hidden, id) };
}

export function reorderGroup(sec: LayoutSection, visible: string[], group: string[]): LayoutSection {
  const members = new Set(group);
  const queue = [...group];
  return { ...sec, order: visible.map((id) => (members.has(id) ? queue.shift()! : id)) };
}

export function moveWithinGroup(group: string[], pinned: string[], id: string, by: -1 | 1): string[] | null {
  const from = group.indexOf(id);
  const to = from + by;
  if (from === -1 || to < 0 || to >= group.length || !sharesPinning(pinned, id, group[to])) return null;
  const next = [...group];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}
