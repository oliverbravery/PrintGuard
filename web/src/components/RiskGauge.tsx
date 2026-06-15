const SWEEP = 240;
const RADIUS = 26;

export function riskColor(score: number, threshold: number): string {
  if (score >= threshold) return "var(--color-bad)";
  if (score >= threshold * 0.7) return "var(--color-warn)";
  return "var(--color-ok)";
}

export function RiskGauge({ score, threshold, size = 76 }: { score: number; threshold: number; size?: number }) {
  const circumference = (SWEEP / 360) * 2 * Math.PI * RADIUS;
  const colour = riskColor(score, threshold);
  const thresholdAngle = ((SWEEP * threshold - SWEEP / 2 - 90) * Math.PI) / 180;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={`risk ${(score * 100).toFixed(0)}%`}>
      <g transform="rotate(-210 32 32)">
        <circle
          cx="32"
          cy="32"
          r={RADIUS}
          fill="none"
          stroke="var(--color-line-0)"
          strokeWidth="5"
          strokeDasharray={`${circumference} 999`}
          strokeLinecap="butt"
        />
        <circle
          cx="32"
          cy="32"
          r={RADIUS}
          fill="none"
          stroke={colour}
          strokeWidth="5"
          strokeDasharray={`${circumference * Math.min(1, score)} 999`}
          strokeLinecap="butt"
          style={{ transition: "stroke-dasharray 400ms ease, stroke 400ms ease" }}
        />
      </g>
      <line
        x1={32 + (RADIUS - 6) * Math.cos(thresholdAngle)}
        y1={32 + (RADIUS - 6) * Math.sin(thresholdAngle)}
        x2={32 + (RADIUS + 5) * Math.cos(thresholdAngle)}
        y2={32 + (RADIUS + 5) * Math.sin(thresholdAngle)}
        stroke="var(--color-text-2)"
        strokeWidth="1.5"
      />
      <text
        x="32"
        y="31"
        textAnchor="middle"
        fill={colour}
        style={{ font: "700 13px var(--font-mono)", transition: "fill 400ms" }}
      >
        {(score * 100).toFixed(0)}
      </text>
      <text x="32" y="42" textAnchor="middle" fill="var(--color-text-2)" style={{ font: "600 6.5px var(--font-display)", letterSpacing: "0.18em" }}>
        RISK
      </text>
    </svg>
  );
}
