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
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {SCHEMES.map((opt) => (
          <button
            key={opt.id}
            aria-pressed={theme === opt.id}
            onClick={() => select(opt.id)}
            className={`flex cursor-pointer flex-col items-center gap-1 rounded border px-2 py-3 transition-colors ${
              theme === opt.id ? "border-accent bg-accent/5 text-text-0" : "border-line-0 text-text-1 hover:border-line-1"
            }`}
          >
            <span className="text-base leading-none">{opt.glyph}</span>
            <span className="text-xs">{opt.name}</span>
          </button>
        ))}
      </div>
      {theme === GLASS && <GlassSliders />}
    </div>
  );
}
