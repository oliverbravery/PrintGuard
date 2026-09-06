import { useId } from "react";

export function Slider({
  label,
  value,
  min,
  max,
  step,
  hint,
  format = (v) => v.toFixed(2),
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  hint?: string;
  format?: (v: number) => string;
  onChange: (v: number) => void;
}) {
  const hintId = useId();
  return (
    <label className="block">
      <div className="flex justify-between mb-1">
        <span className="label">{label}</span>
        <span className="mono text-[0.72rem] text-text-0">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint && <p id={hintId} className="text-[0.7rem] leading-snug text-text-2 mt-1">{hint}</p>}
    </label>
  );
}
