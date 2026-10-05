import type { GroupedBucket } from "../history";
import { riskColor } from "./RiskGauge";

const W = 600;
const CH = 150;
const BH = 44;

function unbrokenRuns(data: GroupedBucket[], span: number): GroupedBucket[][] {
  const runs: GroupedBucket[][] = [];
  for (const bucket of data) {
    const run = runs.at(-1);
    if (run && bucket.t - run.at(-1)!.t <= span) run.push(bucket);
    else runs.push([bucket]);
  }
  return runs;
}

export function RiskBandChart({ data, span, threshold }: { data: GroupedBucket[]; span: number; threshold: number }) {
  const start = data[0].t;
  const width = data[data.length - 1].t - start + span;
  const x = (t: number) => (((t - start + span / 2) / width) * W).toFixed(1);
  const y = (v: number) => (CH - Math.max(0, Math.min(1, v)) * CH).toFixed(1);
  const line = (run: GroupedBucket[], value: (d: GroupedBucket) => number) => run.map((d) => `${x(d.t)},${y(value(d))}`).join(" L");
  const runs = unbrokenRuns(data, span);
  const colour = riskColor(data[data.length - 1].avg, threshold);
  return (
    <svg viewBox={`0 0 ${W} ${CH}`} className="w-full" style={{ height: CH }} preserveAspectRatio="none" role="img" aria-label="Risk over time">
      <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-bad)" strokeOpacity="0.5" strokeWidth="1" strokeDasharray="5 4" />
      {runs.map((run) => (
        <g key={run[0].t}>
          <path d={`M${line(run, (d) => d.max)} L${line([...run].reverse(), (d) => d.min)} Z`} fill={colour} fillOpacity="0.12" stroke="none" />
          <path d={`M${line(run, (d) => d.avg)} h0`} fill="none" stroke={colour} strokeWidth="1.5" strokeLinecap="round" />
        </g>
      ))}
    </svg>
  );
}

export function DefectBars({ data, span }: { data: GroupedBucket[]; span: number }) {
  const start = data[0].t;
  const width = data[data.length - 1].t - start + span;
  const peak = Math.max(1, ...data.map((d) => d.defects));
  const bw = (span / width) * W;
  return (
    <svg viewBox={`0 0 ${W} ${BH}`} className="w-full" style={{ height: BH }} preserveAspectRatio="none" role="img" aria-label="Defect frames per period">
      {data.map((d) => {
        const h = d.defects ? Math.max(2, (d.defects / peak) * BH) : 0;
        return (
          <rect key={d.t} x={((d.t - start) / width) * W} y={BH - h} width={Math.max(1, bw - 1)} height={h} fill="var(--color-bad)" fillOpacity={0.6} />
        );
      })}
    </svg>
  );
}
