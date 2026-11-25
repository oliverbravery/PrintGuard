import { useId } from "react";

export function Toggle({
  label,
  on,
  onChange,
  hint,
  hideLabel = false,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  hideLabel?: boolean;
}) {
  const labelId = useId();
  const hintId = useId();
  return (
    <label className="block cursor-pointer">
      <span className="flex items-center justify-between">
        <span id={labelId} className={hideLabel ? "sr-only" : "text-sm text-text-1"}>
          {label}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby={labelId}
          aria-describedby={hint ? hintId : undefined}
          className="toggle"
          onClick={() => onChange(!on)}
        >
          <span aria-hidden>Off</span>
          <span aria-hidden>On</span>
        </button>
      </span>
      {hint && <p id={hintId} className="text-xs leading-snug text-text-2 mt-1">{hint}</p>}
    </label>
  );
}
