import { formatDuration, formatFilament } from "../prints";
import type { PrintMeta } from "../types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-3 py-2">
      <div className="mono truncate text-sm text-text-0">{value}</div>
      <div className="label mt-0.5">{label}</div>
    </div>
  );
}

export function PrintStats({ meta, temperatures = false }: { meta: PrintMeta | null; temperatures?: boolean }) {
  const degrees = (value?: number | null) => (value ? `${Math.round(value)}°C` : "none");
  const stats: [string, string][] = [
    ["print time", meta?.time_s ? formatDuration(meta.time_s) : "none"],
    ["filament", (meta && formatFilament(meta)) ?? "none"],
    ["sliced for", meta?.printer_model ?? "none"],
    ["slicer", meta?.slicer ?? "none"],
    ...(temperatures ? ([["nozzle", degrees(meta?.nozzle)], ["bed", degrees(meta?.bed)]] as [string, string][]) : []),
  ];
  return (
    <div className={`grid grid-cols-2 gap-2 ${temperatures ? "sm:grid-cols-3" : "sm:grid-cols-4"}`}>
      {stats.map(([label, value]) => (
        <Stat key={label} label={label} value={value} />
      ))}
    </div>
  );
}
