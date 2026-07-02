import type { GroupedBucket } from "../history";
import { riskColor } from "./RiskGauge";

const W = 600;
const CH = 150;
const BH = 44;

export function RiskBandChart({ data, threshold }: { data: GroupedBucket[]; threshold: number }) {
  const n = data.length;
  const x = (i: number) => (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => CH - Math.max(0, Math.min(1, v)) * CH;
  const forward = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.max).toFixed(1)}`).join(" ");
  const backward = data
    .map((d, i) => ({ d, i }))
    .reverse()
    .map(({ d, i }) => `L${x(i).toFixed(1)},${y(d.min).toFixed(1)}`)
    .join(" ");
  const avg = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.avg).toFixed(1)}`).join(" ");
  const colour = riskColor(data[n - 1]?.avg ?? 0, threshold);
  return (
    <svg viewBox={`0 0 ${W} ${CH}`} className="w-full" style={{ height: CH }} preserveAspectRatio="none" role="img" aria-label="Risk over time">
      <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-bad)" strokeOpacity="0.5" strokeWidth="1" strokeDasharray="5 4" />
      <path d={`${forward} ${backward} Z`} fill={colour} fillOpacity="0.12" stroke="none" />
      <path d={avg} fill="none" stroke={colour} strokeWidth="1.5" />
    </svg>
  );
}

export function DefectBars({ data }: { data: GroupedBucket[] }) {
  const n = data.length;
  const peak = Math.max(1, ...data.map((d) => d.defects));
  const bw = W / Math.max(1, n);
  return (
    <svg viewBox={`0 0 ${W} ${BH}`} className="w-full" style={{ height: BH }} preserveAspectRatio="none" role="img" aria-label="Defect frames per period">
      {data.map((d, i) => {
        const h = d.defects ? Math.max(2, (d.defects / peak) * BH) : 0;
        return (
          <rect key={i} x={i * bw} y={BH - h} width={Math.max(1, bw - 1)} height={h} fill="var(--color-bad)" fillOpacity={0.6} />
        );
      })}
    </svg>
  );
}
