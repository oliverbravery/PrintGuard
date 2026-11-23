import { useId } from "react";

export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  hideLabel = false,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
  hideLabel?: boolean;
}) {
  const name = useId();
  return (
    <fieldset className="min-w-0">
      <legend className={hideLabel ? "sr-only" : "label mb-1.5"}>{label}</legend>
      <div className="segmented" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
        {options.map((option) => (
          <label key={option.value}>
            <input type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
