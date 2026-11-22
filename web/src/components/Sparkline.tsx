import type { ScorePoint } from "../types";
import { riskColor } from "./RiskMeter";

const W = 400;
const H = 80;

export function Sparkline({ points, threshold }: { points: ScorePoint[]; threshold: number }) {
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  const latest = points[points.length - 1]?.score ?? 0;
  const colour = riskColor(latest, threshold);
  const path =
    points.length > 1
      ? points
          .map((p, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * W).toFixed(1)},${(H - clamp(p.score) * H).toFixed(1)}`)
          .join(" ")
      : "";
  if (points.length < 2) return <p className="mono flex h-10 items-center text-xs text-text-2">awaiting results</p>;
  const thresholdY = H - clamp(threshold) * H;
  return (
    <svg aria-hidden viewBox={`0 0 ${W} ${H}`} className="h-10 w-full" preserveAspectRatio="none">
      <line
        x1="0"
        x2={W}
        y1={thresholdY}
        y2={thresholdY}
        stroke="var(--color-text-2)"
        strokeWidth="1"
        strokeDasharray="5 4"
      />
      {path && (
        <>
          <path d={`${path} L${W},${H} L0,${H} Z`} fill={colour} fillOpacity="0.08" stroke="none" />
          <path d={path} fill="none" stroke={colour} strokeWidth="1.5" />
        </>
      )}
    </svg>
  );
}
