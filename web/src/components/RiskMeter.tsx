export function riskColor(score: number, threshold: number): string {
  if (score >= threshold) return "var(--color-bad)";
  if (score >= threshold * 0.7) return "var(--color-warn)";
  return "var(--color-ok)";
}

const percent = (value: number) => Math.round(value * 100);

export function RiskMeter({ score, threshold, size = "row" }: { score: number | null; threshold: number; size?: "hero" | "row" }) {
  const colour = score === null ? "var(--color-text-2)" : riskColor(score, threshold);
  const hero = size === "hero";
  return (
    <div role="img" aria-label={score === null ? "risk unknown" : `risk ${percent(score)}%`} className={`flex w-full ${hero ? "items-end gap-4" : "flex-col gap-1"}`}>
      <span className={`mono leading-none ${hero ? "w-[4ch] shrink-0 text-[2.5rem] font-medium tracking-[-0.04em]" : "flex justify-between text-sm font-semibold"}`} style={{ color: colour }}>
        {score === null ? "-" : `${percent(score)}%`}
        {!hero && <span className="text-xs font-normal text-text-2">{percent(threshold)}%</span>}
      </span>
      <span className={`block min-w-0 flex-1 ${hero ? "pb-1" : ""}`}>
        <span className={`relative block border border-line-0 bg-ink-1 ${hero ? "h-2" : "h-1.5"}`}>
          <span className="block h-full transition-[width] duration-500" style={{ width: `${percent(Math.min(1, score ?? 0))}%`, background: colour }} />
          <span className="absolute -inset-y-1 w-0.5 bg-text-0" style={{ left: `${percent(threshold)}%` }} />
        </span>
        {hero && (
          <span aria-hidden className="mono relative mt-1 flex justify-between text-xs text-text-2">
            <span>0</span>
            <span className="absolute -translate-x-1/2" style={{ left: `${percent(threshold)}%` }}>
              {percent(threshold)}
            </span>
            <span>100</span>
          </span>
        )}
      </span>
    </div>
  );
}
