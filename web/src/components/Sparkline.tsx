import type { ScorePoint } from "../types";
import { riskColor } from "./RiskGauge";

const W = 400;
const H = 80;

export function Sparkline({ points, threshold }: { points: ScorePoint[]; threshold: number }) {
  const latest = points[points.length - 1]?.score ?? 0;
  const colour = riskColor(latest, threshold);
  const path =
    points.length > 1
      ? points
          .map((p, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * W).toFixed(1)},${(H - p.score * H).toFixed(1)}`)
          .join(" ")
      : "";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-20" preserveAspectRatio="none">
      <line
        x1="0"
        x2={W}
        y1={H - threshold * H}
        y2={H - threshold * H}
        stroke="var(--color-bad)"
        strokeOpacity="0.5"
        strokeWidth="1"
        strokeDasharray="5 4"
      />
      {path && (
        <>
          <path d={`${path} L${W},${H} L0,${H} Z`} fill={colour} fillOpacity="0.08" stroke="none" />
          <path d={path} fill="none" stroke={colour} strokeWidth="1.5" />
        </>
      )}
      {points.length < 2 && (
        <text x={W / 2} y={H / 2 + 3} textAnchor="middle" fill="var(--color-text-2)" style={{ font: "10px var(--font-mono)" }}>
          awaiting results
        </text>
      )}
    </svg>
  );
}
