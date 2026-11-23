import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { applyTheme, beginPreview, endPreview, GLASS_DEFAULT, PALETTES } from "../theme";
import type { CustomTheme, ThemeBase, ThemeTokenKey } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { SchemePicker } from "./SchemePicker";
import { ThemeEditor } from "./ThemeEditor";

function Swatch({ colors }: { colors: CustomTheme["colors"] }) {
  return (
    <span className="flex overflow-hidden border border-line-1">
      {(["ink0", "accent", "ok", "bad"] as ThemeTokenKey[]).map((k) => (
        <span key={k} className="h-4 w-4" style={{ background: colors[k] }} />
      ))}
    </span>
  );
}

function leavePreview() {
  endPreview();
  const saved = useStore.getState().engine?.settings;
  applyTheme(saved?.theme ?? "system", saved?.themes ?? [], saved?.glass, true);
}

export function AppearanceTab() {
  const { settings, updateSettings } = useStore(useShallow((s) => ({ settings: s.engine?.settings, updateSettings: s.updateSettings })));
  const theme = settings?.theme ?? "system";
  const themes = settings?.themes ?? [];
  const glass = { ...GLASS_DEFAULT, ...settings?.glass };
  const [editing, setEditing] = useState<CustomTheme | null>(null);

  const upsertTheme = (list: CustomTheme[], t: CustomTheme) =>
    list.some((x) => x.id === t.id) ? list.map((x) => (x.id === t.id ? t : x)) : [...list, t];
  const selectTheme = (id: string) => {
    applyTheme(id, themes, glass, true);
    updateSettings({ theme: id });
  };
  const newTheme = (base: ThemeBase) => setEditing({ id: "t" + Date.now().toString(36), name: "", base, colors: { ...PALETTES[base] } });
  const cancelEdit = () => {
    leavePreview();
    setEditing(null);
  };
  const saveTheme = () => {
    if (!editing) return;
    const next = upsertTheme(themes, { ...editing, name: editing.name.trim() || "Custom" });
    endPreview();
    applyTheme(editing.id, next, glass, true);
    updateSettings({ themes: next, theme: editing.id });
    setEditing(null);
  };
  const deleteTheme = (id: string) => {
    const next = themes.filter((t) => t.id !== id);
    const selection = theme === id ? "system" : theme;
    applyTheme(selection, next, glass, true);
    updateSettings({ themes: next, theme: selection });
  };

  useEffect(() => {
    if (!editing) return;
    beginPreview();
    applyTheme(editing.id, upsertTheme(themes, editing), glass, true);
  }, [editing]);

  const editingRef = useRef(editing);
  editingRef.current = editing;
  useEffect(
    () => () => {
      if (editingRef.current) leavePreview();
    },
    [],
  );

  if (editing)
    return <ThemeEditor value={editing} onChange={setEditing} onSave={saveTheme} onCancel={cancelEdit} canSave={!!editing.name.trim()} />;
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <span className="label block">Theme</span>
        <SchemePicker />
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="label block">Custom themes</span>
          <button className="btn" onClick={() => newTheme(theme === "light" ? "light" : "dark")}>
            + New
          </button>
        </div>
        {themes.length === 0 && <p className="text-sm text-text-2">No custom themes yet. Create one to customise every colour.</p>}
        <div className="border-t border-line-0">
          {themes.map((t) => (
            <div key={t.id} className="flex items-center gap-2 border-b border-line-0 py-2">
              <button
                onClick={() => selectTheme(t.id)}
                aria-pressed={theme === t.id}
                className="flex min-h-11 flex-1 cursor-pointer items-center gap-3 overflow-hidden px-2 text-left hover:bg-ink-1 aria-pressed:bg-ink-3 aria-pressed:shadow-[inset_3px_0_0_var(--color-accent)]"
              >
                <Swatch colors={t.colors} />
                <span className="flex-1 truncate text-sm">{t.name}</span>
                <span className="chip">{t.base}</span>
              </button>
              <button className="btn" onClick={() => setEditing({ ...t, colors: { ...PALETTES[t.base], ...t.colors } })}>
                Edit
              </button>
              <ConfirmButton onConfirm={() => deleteTheme(t.id)}>Delete</ConfirmButton>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
