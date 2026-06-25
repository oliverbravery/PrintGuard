import { useEffect, useState } from "react";
import { PALETTES, TOKEN_GROUPS } from "../theme";
import type { CustomTheme, ThemeBase, ThemeTokenKey } from "../types";

function ColorField({ value, onChange }: { value: string; onChange: (hex: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = (raw: string) => {
    setText(raw);
    if (/^#[0-9a-fA-F]{6}$/.test(raw)) onChange(raw.toLowerCase());
  };
  return (
    <div className="flex shrink-0 items-center gap-2">
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-7 w-8 cursor-pointer rounded border border-line-1 bg-transparent p-0"
        aria-label="Colour"
      />
      <input className="field mono" style={{ width: "5.5rem" }} value={text} spellCheck={false} onChange={(e) => commit(e.target.value)} />
    </div>
  );
}

export function ThemeEditor({
  value,
  onChange,
  onSave,
  onCancel,
  canSave,
}: {
  value: CustomTheme;
  onChange: (theme: CustomTheme) => void;
  onSave: () => void;
  onCancel: () => void;
  canSave: boolean;
}) {
  const setColor = (key: ThemeTokenKey, hex: string) => onChange({ ...value, colors: { ...value.colors, [key]: hex } });
  const setBase = (base: ThemeBase) => onChange({ ...value, base, colors: { ...PALETTES[base] } });

  return (
    <div className="space-y-5">
      <div className="flex gap-2">
        <input
          className="field flex-1"
          placeholder="Theme name"
          value={value.name}
          autoFocus
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
        <select className="field shrink-0" style={{ width: "8rem" }} value={value.base} onChange={(e) => setBase(e.target.value as ThemeBase)}>
          <option value="dark">From dark</option>
          <option value="light">From light</option>
        </select>
      </div>

      {TOKEN_GROUPS.map((group) => (
        <div key={group.label} className="space-y-2">
          <span className="label block">{group.label}</span>
          {group.tokens.map((token) => (
            <div key={token.key} className="flex items-center justify-between gap-3">
              <span className="text-xs text-text-1">{token.label}</span>
              <ColorField value={value.colors[token.key]} onChange={(hex) => setColor(token.key, hex)} />
            </div>
          ))}
        </div>
      ))}

      <span className="block text-[0.7rem] text-text-2">Changes preview live. Save to keep this theme and switch to it.</span>
      <div className="flex gap-2">
        <button className="btn flex-1" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary flex-1" disabled={!canSave} onClick={onSave}>
          Save theme
        </button>
      </div>
    </div>
  );
}
