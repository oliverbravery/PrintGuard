import type { HistoryBucket } from "./types";

export type Period = "1h" | "6h" | "24h" | "all";

export const PERIODS: Period[] = ["1h", "6h", "24h", "all"];

const WINDOW_S: Record<Period, number> = { "1h": 3600, "6h": 21600, "24h": 86400, all: Infinity };
const GROUP_S: Record<Period, number> = { "1h": 60, "6h": 300, "24h": 900, all: 3600 };

export interface GroupedBucket {
  t: number;
  avg: number;
  min: number;
  max: number;
  defects: number;
  n: number;
}

export function groupBuckets(buckets: HistoryBucket[], period: Period, now: number): GroupedBucket[] {
  const cutoff = now - WINDOW_S[period];
  const span = GROUP_S[period];
  const groups = new Map<number, GroupedBucket & { sum: number }>();
  for (const b of buckets) {
    if (b.t < cutoff) continue;
    const key = Math.floor(b.t / span) * span;
    const g = groups.get(key);
    if (!g) {
      groups.set(key, { t: key, avg: 0, min: b.min, max: b.max, defects: b.defects, n: b.n, sum: b.sum });
    } else {
      g.min = Math.min(g.min, b.min);
      g.max = Math.max(g.max, b.max);
      g.defects += b.defects;
      g.n += b.n;
      g.sum += b.sum;
    }
  }
  return [...groups.values()]
    .sort((a, b) => a.t - b.t)
    .map(({ sum, ...g }) => ({ ...g, avg: g.n ? sum / g.n : 0 }));
}
