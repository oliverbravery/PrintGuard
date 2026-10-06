import { useId } from "react";
import type { AdapterConfig, AdapterMeta } from "../types";
import { ExperimentalBadge } from "./ExperimentalBadge";
import { NewTab } from "./NewTab";
import { SecretInput } from "./SecretInput";

export function withoutSecrets(meta: AdapterMeta | undefined, config: AdapterConfig): AdapterConfig {
  return Object.fromEntries(Object.entries(config).filter(([key]) => !meta?.schema.properties[key]?.secret));
}

export function SchemaForm({
  meta,
  value,
  saved = [],
  onChange,
}: {
  meta: AdapterMeta;
  value: AdapterConfig;
  saved?: string[];
  onChange: (next: AdapterConfig) => void;
}) {
  const formId = useId();
  const required = meta.schema.required ?? [];
  const setField = (key: string, next: string | null | undefined) => {
    const { [key]: _previous, ...rest } = value;
    onChange(next === undefined ? rest : { ...value, [key]: next });
  };
  return (
    <div className="space-y-3">
      {meta.experimental && <ExperimentalBadge detail />}
      {meta.setup_hint && <p className="text-[0.7rem] leading-snug text-text-2">{meta.setup_hint}</p>}
      {Object.entries(meta.schema.properties).map(([key, prop]) => (
        <div key={key}>
          <label className="label block mb-1" htmlFor={formId + key}>
            {prop.title}
            {required.includes(key) && <span className="text-accent"> *</span>}
          </label>
          {prop.enum ? (
            <select id={formId + key} className="field" value={value[key] ?? prop.default ?? ""} onChange={(e) => setField(key, e.target.value)}>
              {prop.default === undefined && <option value="">Select…</option>}
              {prop.enum.map((option, index) => (
                <option key={option} value={option}>
                  {prop.enum_labels?.[index] ?? option}
                </option>
              ))}
            </select>
          ) : prop.secret ? (
            <SecretInput
              id={formId + key}
              name={prop.title}
              saved={saved.includes(key)}
              value={value[key]}
              placeholder={prop.placeholder}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              onChange={(next) => setField(key, next)}
            />
          ) : (
            <input
              id={formId + key}
              className="field"
              type="text"
              placeholder={prop.placeholder}
              value={value[key] ?? ""}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => setField(key, e.target.value)}
            />
          )}
        </div>
      ))}
      <a href={meta.setup_url ?? meta.docs_url} target="_blank" rel="noreferrer" className="mono text-[0.64rem] text-text-2 hover:text-accent inline-block">
        {meta.label} {meta.setup_url ? "setup guide" : "API docs"} <NewTab />
      </a>
    </div>
  );
}
