export function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between cursor-pointer">
      <span className="text-sm text-text-1">{label}</span>
      <button type="button" className="toggle" data-on={on} onClick={() => onChange(!on)} />
    </label>
  );
}
