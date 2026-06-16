import type { AdapterMeta } from "../types";
import { ExperimentalBadge } from "./ExperimentalBadge";

export function SchemaForm({
  meta,
  value,
  onChange,
}: {
  meta: AdapterMeta;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const required = meta.schema.required ?? [];
  return (
    <div className="space-y-3">
      {meta.experimental && <ExperimentalBadge detail />}
      {meta.setup_hint && <p className="text-[0.7rem] leading-snug text-text-2">{meta.setup_hint}</p>}
      {Object.entries(meta.schema.properties).map(([key, prop]) => (
        <label key={key} className="block">
          <span className="label block mb-1">
            {prop.title}
            {required.includes(key) && <span className="text-accent"> *</span>}
          </span>
          <input
            className="field"
            type={prop.secret ? "password" : "text"}
            placeholder={prop.placeholder}
            value={value[key] ?? ""}
            autoComplete="off"
            onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          />
        </label>
      ))}
      <a href={meta.setup_url ?? meta.docs_url} target="_blank" rel="noreferrer" className="mono text-[0.64rem] text-text-2 hover:text-accent inline-block">
        {meta.label} {meta.setup_url ? "setup guide" : "API docs"} ↗
      </a>
    </div>
  );
}
