import { useId, useRef, type InputHTMLAttributes } from "react";

const KEPT = "Saved. Leave blank to keep it";
const CLEARED = "Will be removed on Save";
const RETYPE = "Type it again, the address changed";

export function SecretInput({
  name,
  saved,
  retype = false,
  value,
  onChange,
  placeholder,
  className = "",
  ...input
}: {
  name: string;
  saved: boolean;
  retype?: boolean;
  value: string | null | undefined;
  onChange: (next: string | null | undefined) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const hintId = useId();
  const field = useRef<HTMLInputElement>(null);
  const hint = !saved || value ? null : value === null ? CLEARED : retype ? RETYPE : KEPT;
  return (
    <div className="flex min-w-0 flex-1 basis-56 items-center gap-2">
      <input
        {...input}
        ref={field}
        className={`field min-w-0 flex-1 ${className}`}
        type="password"
        autoComplete="off"
        placeholder={hint ?? placeholder}
        aria-describedby={hint ? hintId : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      />
      {hint && (
        <span id={hintId} className="sr-only">
          {hint}
        </span>
      )}
      {hint === KEPT && (
        <button
          type="button"
          className="btn tap-target shrink-0"
          aria-label={`Remove the stored ${name}`}
          onClick={() => {
            onChange(null);
            field.current?.focus();
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}
