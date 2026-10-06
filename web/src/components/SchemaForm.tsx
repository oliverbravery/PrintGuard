import { useId } from "react";
import type { AdapterConfig, AdapterMeta } from "../types";
import { ExperimentalBadge } from "./ExperimentalBadge";
import { NewTab } from "./NewTab";
import { SecretInput } from "./SecretInput";

const ADDRESS_FIELDS = ["base_url", "host", "port", "url"];
const REDACTED = "[redacted]";

const shown = (config: object, key: string) => String((config as Record<string, unknown>)[key] ?? "");

export function addressMoved(value: object, stored: object): boolean {
  return ADDRESS_FIELDS.some((key) => shown(value, key) !== shown(stored, key));
}

export function savedSecretTitles(meta: AdapterMeta, saved: string[]): Record<string, string> {
  return Object.fromEntries(saved.map((key) => [key, meta.schema.properties[key]?.title ?? key]));
}

export function retypeReason(value: object, stored: object, savedSecrets: Record<string, string>): string | null {
  if (ADDRESS_FIELDS.some((key) => shown(value, key).includes(REDACTED) && shown(value, key) !== shown(stored, key)))
    return `The address still has ${REDACTED} in it. Type the whole address.`;
  const blank = Object.entries(savedSecrets).filter(([key]) => (value as Record<string, unknown>)[key] !== null && !shown(value, key));
  if (blank.length && addressMoved(value, stored)) return `Retype ${blank.map(([, title]) => title).join(" and ")}, since the address changed.`;
  return null;
}

export function SchemaForm({
  meta,
  value,
  stored,
  saved = [],
  onChange,
}: {
  meta: AdapterMeta;
  value: AdapterConfig;
  stored?: object;
  saved?: string[];
  onChange: (next: AdapterConfig) => void;
}) {
  const formId = useId();
  const required = meta.schema.required ?? [];
  const moved = stored !== undefined && addressMoved(value, stored);
  const setField = (key: string, next: string | null | undefined) => {
    const { [key]: _previous, ...rest } = value;
    onChange(next === undefined ? rest : { ...value, [key]: next });
  };
  return (
    <div className="space-y-3">
      {meta.experimental && <ExperimentalBadge />}
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
              retype={moved}
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
          {!prop.secret && stored !== undefined && ADDRESS_FIELDS.includes(key) && shown(value, key) !== shown(stored, key) && (
            <span className="mt-1 block text-[0.7rem] text-text-2">The saved address may hide a login or key, so type the whole address.</span>
          )}
        </div>
      ))}
      <a href={meta.setup_url ?? meta.docs_url} target="_blank" rel="noreferrer" className="mono text-[0.64rem] text-text-2 hover:text-accent inline-block">
        {meta.label} {meta.setup_url ? "setup guide" : "API docs"} <NewTab />
      </a>
    </div>
  );
}
