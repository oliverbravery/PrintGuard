export function TestRow({
  label,
  busyLabel,
  busy,
  disabled,
  onTest,
  result,
}: {
  label: string;
  busyLabel: string;
  busy: boolean;
  disabled: boolean;
  onTest: () => void;
  result: { ok: boolean; message: string } | null;
}) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <button className="btn shrink-0" disabled={disabled} onClick={onTest}>
        {busy ? busyLabel : label}
      </button>
      {result && <span className={`chip chip-message ${result.ok ? "chip-ok" : "chip-bad"}`}>{result.message}</span>}
    </div>
  );
}
