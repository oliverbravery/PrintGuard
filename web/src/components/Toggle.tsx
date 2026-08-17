import { useId } from "react";

export function Toggle({
  label,
  on,
  onChange,
  hideLabel = false,
}: {
  label: string;
  on: boolean;
  onChange: (v: boolean) => void;
  hideLabel?: boolean;
}) {
  const labelId = useId();
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span id={labelId} className={hideLabel ? "sr-only" : "text-sm text-text-1"}>
        {label}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-labelledby={labelId}
        className="toggle"
        data-on={on}
        onClick={() => onChange(!on)}
      />
    </label>
  );
}
