import { useStore } from "../store";
import { applyTheme, GLASS } from "../theme";
import { GlassSliders } from "./GlassTuner";

const SCHEMES: { id: string; name: string; glyph: string }[] = [
  { id: "system", name: "System", glyph: "◐" },
  { id: "light", name: "Light", glyph: "☀" },
  { id: "dark", name: "Dark", glyph: "☾" },
  { id: GLASS, name: "Glass", glyph: "◈" },
];

export function SchemePicker() {
  const theme = useStore((s) => s.engine?.settings.theme ?? "system");
  const themes = useStore((s) => s.engine?.settings.themes ?? []);
  const glass = useStore((s) => s.engine?.settings.glass);
  const updateSettings = useStore((s) => s.updateSettings);
  const select = (id: string) => {
    applyTheme(id, themes, glass, true);
    updateSettings({ theme: id });
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-px border border-line-1 bg-line-0 sm:grid-cols-4">
        {SCHEMES.map((opt) => (
          <button
            key={opt.id}
            aria-pressed={theme === opt.id}
            onClick={() => select(opt.id)}
            className="flex min-h-16 cursor-pointer flex-col items-center justify-center gap-1 bg-ink-0 px-2 py-3 text-text-1 hover:bg-ink-1 hover:text-text-0 aria-pressed:bg-text-0 aria-pressed:text-ink-0"
          >
            <span className="text-base leading-none">{opt.glyph}</span>
            <span className="mono text-xs font-medium uppercase tracking-[0.06em]">{opt.name}</span>
          </button>
        ))}
      </div>
      {theme === GLASS && <GlassSliders />}
    </div>
  );
}
