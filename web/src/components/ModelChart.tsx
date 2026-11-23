import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { BENCHMARKS, FAMILIES, GOLD_TEST, type Benchmark, type ModelFamily, type ModelId } from "../models";

type Key = Benchmark["id"] | ModelFamily;

interface Metric {
  id: string;
  label: string;
  value: (model: Benchmark) => number;
  max: number;
  ticks: number[];
  tick: (value: number) => string;
  format: (value: number) => string;
}

interface Placed {
  model: Benchmark;
  x: number;
  y: number;
  label: { x: number; y: number; w: number; h: number };
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const QUARTERS = [0, 0.25, 0.5, 0.75, 1];
const METRICS: Metric[] = [
  { id: "caught", label: "Failed prints caught", value: (m) => m.caught, max: GOLD_TEST.failedPrints, ticks: [0, 5, 10, 15, 20], tick: String, format: (v) => `${v} of ${GOLD_TEST.failedPrints}` },
  { id: "pr", label: "PR-AUC", value: (m) => m.pr, max: 1, ticks: QUARTERS, tick: (v) => v.toFixed(2), format: (v) => v.toFixed(3) },
  { id: "roc", label: "ROC-AUC", value: (m) => m.roc, max: 1, ticks: QUARTERS, tick: (v) => v.toFixed(2), format: (v) => v.toFixed(3) },
  { id: "r80", label: "Recall at 80% precision", value: (m) => m.r80, max: 1, ticks: QUARTERS, tick: (v) => `${v * 100}%`, format: percent },
  { id: "r90", label: "Recall at 90% precision", value: (m) => m.r90, max: 1, ticks: QUARTERS, tick: (v) => `${v * 100}%`, format: percent },
];
const X_TICKS = [3, 10, 30, 100, 300, 1000];
const X_MIN = 3;
const X_MAX = 1000;
const HEIGHT = 300;
const MARGIN = { top: 30, right: 14, bottom: 44, left: 40 };
const LABEL_FONT = 12;
let measure: CanvasRenderingContext2D | null = null;

function textWidth(text: string, family: string): number {
  measure ??= document.createElement("canvas").getContext("2d");
  if (!measure) return text.length * 7;
  measure.font = `500 ${LABEL_FONT}px ${family}`;
  return measure.measureText(text).width + 2;
}

function shapePath(shape: "circle" | "square" | "diamond", r: number): string {
  if (shape === "square") return `M${-r},${-r}h${2 * r}v${2 * r}h${-2 * r}z`;
  if (shape === "diamond") {
    const d = r * 1.3;
    return `M0,${-d}L${d},0L0,${d}L${-d},0z`;
  }
  return `M${-r},0a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`;
}

function Swatch({ family, size = 14 }: { family: ModelFamily; size?: number }) {
  return (
    <svg className="shrink-0" width={size} height={size} viewBox={`${-size / 2} ${-size / 2} ${size} ${size}`} aria-hidden>
      <path d={shapePath(FAMILIES[family].shape, size / 2 - 2.5)} fill={FAMILIES[family].colour} />
    </svg>
  );
}

const overlaps = (a: Placed["label"], b: Placed["label"]) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function placeLabels(points: Omit<Placed, "label">[], bounds: { left: number; top: number; right: number; bottom: number }, family: string, first: (m: Benchmark) => boolean): Placed[] {
  const boxes: Placed["label"][] = [];
  const marks = points.map((p) => ({ x: p.x - 9, y: p.y - 9, w: 18, h: 18 }));
  const placed = new Map<string, Placed["label"]>();
  for (const p of [...points].sort((a, b) => Number(first(b.model)) - Number(first(a.model)))) {
    const w = textWidth(p.model.short, family);
    const h = LABEL_FONT + 2;
    const gap = 15;
    const candidates = [
      { x: p.x + gap, y: p.y - h / 2 },
      { x: p.x - gap - w, y: p.y - h / 2 },
      { x: p.x - w / 2, y: p.y - gap - h },
      { x: p.x - w / 2, y: p.y + gap },
      { x: p.x + gap - 2, y: p.y - gap - h + 2 },
      { x: p.x + gap - 2, y: p.y + gap - 2 },
      { x: p.x - gap - w + 2, y: p.y - gap - h + 2 },
      { x: p.x - gap - w + 2, y: p.y + gap - 2 },
    ].map((c) => ({ ...c, w, h }));
    const cost = (c: Placed["label"]) =>
      (c.x < bounds.left || c.x + c.w > bounds.right || c.y < bounds.top || c.y + c.h > bounds.bottom ? 100 : 0) +
      [...marks, ...boxes].filter((other) => overlaps(c, other)).length * 10;
    const best = candidates.reduce((a, b) => (cost(b) < cost(a) ? b : a));
    boxes.push(best);
    placed.set(p.model.id, best);
  }
  return points.map((p) => ({ ...p, label: placed.get(p.model.id)! }));
}

function activate(toggle: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggle();
  };
}

export function ModelChart({ selected }: { selected?: ModelId }) {
  const frame = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [metric, setMetric] = useState(METRICS[0]);
  const [pinned, setPinned] = useState<Key | null>(null);
  const [preview, setPreview] = useState<Key | null>(null);
  const [hover, setHover] = useState<Benchmark["id"] | null>(null);

  useLayoutEffect(() => {
    const element = frame.current!;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const focus = preview ?? pinned;
  const matches = (model: Benchmark, key: Key | null) => !key || key === model.id || key === model.family;
  const toggle = (key: Key) => {
    setPinned(pinned === key ? null : key);
    setPreview(null);
  };

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const sx = (ms: number) => MARGIN.left + ((Math.log10(ms) - Math.log10(X_MIN)) / (Math.log10(X_MAX) - Math.log10(X_MIN))) * plotWidth;
  const sy = (value: number) => MARGIN.top + plotHeight - (value / metric.max) * plotHeight;
  const family = frame.current ? getComputedStyle(frame.current).fontFamily : "sans-serif";
  const points = width
    ? placeLabels(
        BENCHMARKS.map((model) => ({ model, x: sx(model.ms), y: sy(metric.value(model)) })),
        { left: MARGIN.left, top: MARGIN.top, right: width - MARGIN.right, bottom: MARGIN.top + plotHeight },
        family,
        (model) => matches(model, focus),
      )
    : [];
  const tipped = points.find((p) => p.model.id === (hover ?? (BENCHMARKS.some((m) => m.id === focus) ? focus : null)));

  useLayoutEffect(() => {
    const box = tip.current;
    if (!box || !tipped) return;
    let left = tipped.x + 16;
    if (left + box.offsetWidth > width) left = tipped.x - 16 - box.offsetWidth;
    if (left < 0) left = Math.max(0, Math.min(width - box.offsetWidth, tipped.x - box.offsetWidth / 2));
    box.style.left = `${left}px`;
    box.style.top = `${Math.max(0, Math.min(HEIGHT - box.offsetHeight, tipped.y - box.offsetHeight / 2))}px`;
  });

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Metric on the vertical axis">
        {METRICS.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={metric.id === option.id}
            onClick={() => setMetric(option)}
            className={`cursor-pointer border px-2 py-1 text-xs transition-colors ${
              metric.id === option.id ? "border-accent bg-accent/5 text-text-0" : "border-line-0 text-text-1 hover:border-line-1"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {(Object.keys(FAMILIES) as ModelFamily[]).map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={pinned === key}
            onClick={() => toggle(key)}
            onPointerEnter={() => setPreview(key)}
            onPointerLeave={() => setPreview(null)}
            className={`inline-flex cursor-pointer items-center gap-1.5 border px-1.5 py-0.5 text-xs text-text-0 ${
              pinned === key ? "border-line-1 bg-text-0/5" : "border-transparent"
            }`}
          >
            <Swatch family={key} />
            {FAMILIES[key].name}
          </button>
        ))}
      </div>
      <div ref={frame} className="relative">
        <svg
          className="block w-full touch-manipulation"
          style={{ height: HEIGHT }}
          viewBox={`0 0 ${Math.max(width, 1)} ${HEIGHT}`}
          role="group"
          aria-label={`${metric.label} against latency for each model`}
          onClick={() => pinned && toggle(pinned)}
        >
          {width > 0 && (
            <>
              <g className="fill-text-2 text-[11px]">
                {metric.ticks.map((t) => (
                  <g key={t}>
                    <line className="stroke-line-0" x1={MARGIN.left} x2={width - MARGIN.right} y1={sy(t)} y2={sy(t)} />
                    <text x={MARGIN.left - 6} y={sy(t) + 4} textAnchor="end">
                      {metric.tick(t)}
                    </text>
                  </g>
                ))}
                {X_TICKS.map((t) => (
                  <g key={t}>
                    <line className="stroke-line-0" x1={sx(t)} x2={sx(t)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} strokeDasharray="2 3" />
                    <text x={sx(t)} y={MARGIN.top + plotHeight + 16} textAnchor={t === X_MAX ? "end" : "middle"}>
                      {t}
                    </text>
                  </g>
                ))}
                <text x={MARGIN.left + plotWidth / 2} y={HEIGHT - 6} textAnchor="middle">
                  Milliseconds per frame on one CPU thread, log scale
                </text>
                <text x={MARGIN.left - 34} y={14}>
                  {metric.label}
                </text>
                <text x={width - MARGIN.right} y={14} textAnchor="end">
                  Higher and further left is better
                </text>
              </g>
              {points.map((p) => (
                <text
                  key={p.model.id}
                  className={`pointer-events-none fill-text-0 font-medium transition-opacity ${!matches(p.model, focus) && hover !== p.model.id ? "opacity-20" : ""}`}
                  style={{ fontSize: LABEL_FONT }}
                  x={p.label.x}
                  y={p.label.y + LABEL_FONT - 1}
                >
                  {p.model.short}
                </text>
              ))}
              {points.map((p) => {
                const ringed = focus === p.model.id || hover === p.model.id || selected === p.model.id;
                return (
                  <g
                    key={p.model.id}
                    className={`cursor-pointer outline-none transition-opacity ${!matches(p.model, focus) && hover !== p.model.id ? "opacity-20" : ""}`}
                    transform={`translate(${p.x},${p.y})`}
                    tabIndex={0}
                    role="button"
                    aria-label={`${p.model.name}, ${metric.label} ${metric.format(metric.value(p.model))}, ${p.model.ms} ms${selected === p.model.id ? ", in use" : ""}`}
                    onPointerEnter={() => setHover(p.model.id)}
                    onPointerLeave={() => setHover(null)}
                    onFocus={() => setHover(p.model.id)}
                    onBlur={() => setHover(null)}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggle(p.model.id);
                    }}
                    onKeyDown={activate(() => toggle(p.model.id))}
                  >
                    <circle r={16} fill="transparent" />
                    <circle r={11} fill="none" strokeWidth={1.5} stroke={ringed ? "var(--color-text-0)" : "transparent"} />
                    <path d={shapePath(FAMILIES[p.model.family].shape, 6)} fill={FAMILIES[p.model.family].colour} stroke="var(--color-ink-1)" strokeWidth={2} />
                  </g>
                );
              })}
            </>
          )}
        </svg>
        {tipped && (
          <div ref={tip} className="pointer-events-none absolute z-10 min-w-48 border border-line-1 bg-ink-2 px-3 py-2.5 text-xs shadow-lg">
            <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-text-0">
              <Swatch family={tipped.model.family} size={12} />
              {tipped.model.name}
            </div>
            {[
              [metric.label, metric.format(metric.value(tipped.model))],
              ["Latency", `${tipped.model.ms} ms`],
              ["Size", `${tipped.model.mb} MB`],
              ...METRICS.filter((other) => other !== metric).map((other) => [other.label, other.format(other.value(tipped.model))]),
              ["Good prints alarmed", `${tipped.model.alarmed} of ${GOLD_TEST.goodPrints}`],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 leading-relaxed">
                <span className="text-text-2">{label}</span>
                <strong className="font-semibold text-text-0">{value}</strong>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="overflow-x-auto border border-line-0">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="text-text-2">
              {["Model", "Size", "Latency", "PR-AUC", "ROC", "R@80P", "R@90P", "Caught", "False alarms"].map((heading, i) => (
                <th key={heading} className={`border-b border-line-0 px-2 py-1.5 font-medium ${i ? "text-right" : "text-left"}`}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {BENCHMARKS.map((model) => (
              <tr
                key={model.id}
                tabIndex={0}
                className={`cursor-pointer border-b border-line-0 transition-opacity last:border-b-0 ${focus && matches(model, focus) ? "bg-text-0/5" : ""} ${focus && !matches(model, focus) ? "opacity-20" : ""}`}
                onClick={() => toggle(model.id)}
                onKeyDown={activate(() => toggle(model.id))}
                onPointerEnter={() => setPreview(model.id)}
                onPointerLeave={() => setPreview(null)}
              >
                <td className="px-2 py-1.5 text-left text-text-0">
                  <span className="inline-flex items-center gap-1.5">
                    <Swatch family={model.family} size={12} />
                    {model.name}
                  </span>
                </td>
                {[`${model.mb} MB`, `${model.ms} ms`, model.pr.toFixed(3), model.roc.toFixed(3), percent(model.r80), percent(model.r90), `${model.caught}/${GOLD_TEST.failedPrints}`, `${model.alarmed}/${GOLD_TEST.goodPrints}`].map((cell, i) => (
                  <td key={i} className="mono px-2 py-1.5 text-right text-text-1">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs leading-relaxed text-text-2">
        Tested on {GOLD_TEST.frames.toLocaleString("en-GB")} curated frames from {GOLD_TEST.hubs} PrintGuard hubs none of the models had seen before,
        with latency measured on one CPU thread of an M1 Max. Caught and false alarms count whole prints ({GOLD_TEST.failedPrints} failed and{" "}
        {GOLD_TEST.goodPrints} good), alerting after 3 frames in a row at 0.75. Obico's scores aren't probabilities, so its thresholds were
        matched on separate validation frames.
      </p>
    </div>
  );
}
