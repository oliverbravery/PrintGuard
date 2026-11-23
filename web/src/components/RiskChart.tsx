import type { GroupedBucket } from "../history";
import { riskColor } from "./RiskMeter";

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

function acrossItsSpan(bucket: GroupedBucket, span: number): GroupedBucket[] {
  return [-span / 2, span / 2].map((offset) => ({ ...bucket, t: bucket.t + offset }));
}

const RISK_TICKS = [1, 0.75, 0.5, 0.25, 0];
const TIME_TICKS = 5;

function RiskBandChart({ data, span, threshold }: { data: GroupedBucket[]; span: number; threshold: number }) {
  const start = data[0].t;
  const width = data[data.length - 1].t - start + span;
  const x = (t: number) => (((t - start + span / 2) / width) * W).toFixed(1);
  const y = (v: number) => (CH - Math.max(0, Math.min(1, v)) * CH).toFixed(1);
  const line = (run: GroupedBucket[], value: (d: GroupedBucket) => number) => run.map((d) => `${x(d.t)},${y(value(d))}`).join(" L");
  const runs = unbrokenRuns(data, span).map((run) => (run.length > 1 ? run : acrossItsSpan(run[0], span)));
  const colour = riskColor(data[data.length - 1].avg, threshold);
  return (
    <svg viewBox={`0 0 ${W} ${CH}`} className="w-full border-b border-l border-line-1" style={{ height: CH }} preserveAspectRatio="none" role="img" aria-label="Risk over time">
      {RISK_TICKS.slice(1, -1).map((risk) => (
        <line key={risk} x1="0" x2={W} y1={y(risk)} y2={y(risk)} stroke="var(--color-line-0)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      ))}
      <line x1="0" x2={W} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-bad)" strokeOpacity="0.5" strokeWidth="1" strokeDasharray="5 4" />
      {runs.map((run) => (
        <g key={run[0].t}>
          <path d={`M${line(run, (d) => d.max)} L${line([...run].reverse(), (d) => d.min)} Z`} fill={colour} fillOpacity="0.12" stroke="none" />
          <path d={`M${line(run, (d) => d.avg)}`} fill="none" stroke={colour} strokeWidth="1.5" strokeLinecap="round" />
        </g>
      ))}
    </svg>
  );
}

function DefectBars({ data, span }: { data: GroupedBucket[]; span: number }) {
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

export function RiskPeriodChart({ data, span, threshold, time }: { data: GroupedBucket[]; span: number; threshold: number; time: (ts: number) => string }) {
  const start = data[0].t;
  const width = data[data.length - 1].t - start + span;
  const peak = Math.max(1, ...data.map((d) => d.defects));
  const ticks = Array.from({ length: TIME_TICKS }, (_, index) => index / (TIME_TICKS - 1));
  return (
    <div className="@container grid grid-cols-[3rem_minmax(0,1fr)] gap-y-2">
      <div aria-hidden className="mono relative text-xs text-text-2" style={{ height: CH }}>
        {RISK_TICKS.map((risk) => (
          <span key={risk} className="absolute right-2" style={{ top: `${(1 - risk) * 100}%`, translate: `0 ${risk === 1 ? "0" : risk === 0 ? "-100%" : "-50%"}` }}>
            {risk * 100}%
          </span>
        ))}
      </div>
      <RiskBandChart data={data} span={span} threshold={threshold} />
      <div aria-hidden className="mono flex flex-col justify-between pr-2 text-right text-xs text-text-2">
        <span>{peak}</span>
        <span>0</span>
      </div>
      <DefectBars data={data} span={span} />
      <span />
      <div aria-hidden className="mono relative h-4 text-xs text-text-2">
        {ticks.map((at, index) => (
          <span
            key={at}
            className={`absolute whitespace-nowrap ${index % 2 ? "@max-2xl:hidden" : ""}`}
            style={{ left: `${at * 100}%`, translate: index === 0 ? "0" : index === TIME_TICKS - 1 ? "-100%" : "-50%" }}
          >
            {time(start + width * at)}
          </span>
        ))}
      </div>
    </div>
  );
}
