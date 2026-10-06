import { useStore } from "../store";
import { applyTheme, GLASS_DEFAULT } from "../theme";
import type { Glass } from "../types";

export const GLASS_TUNER = "glass-tuner";

const SLIDERS: { key: keyof Glass; label: string; low: string; high: string }[] = [
  { key: "opacity", label: "Opacity", low: "Clear", high: "Solid" },
  { key: "tone", label: "Tone", low: "Black", high: "White" },
];

const percent = (value: number) => `${Math.round(value * 100)}%`;

export function GlassSliders() {
  const stored = useStore((s) => s.engine?.settings.glass);
  const glass = { ...GLASS_DEFAULT, ...stored };
  const theme = useStore((s) => s.engine?.settings.theme ?? "system");
  const themes = useStore((s) => s.engine?.settings.themes ?? []);
  const updateSettings = useStore((s) => s.updateSettings);
  const slide = (key: keyof Glass, value: number) => {
    const next = { ...glass, [key]: value };
    applyTheme(theme, themes, next);
    updateSettings({ glass: next });
  };
  return (
    <div className="space-y-3">
      {SLIDERS.map((slider) => (
        <div key={slider.key}>
          <div className="flex items-baseline justify-between">
            <span className="label">{slider.label}</span>
            <span className="mono text-[0.7rem] text-text-2">{percent(glass[slider.key])}</span>
          </div>
          <input
            type="range"
            className="slider"
            min={0}
            max={1}
            step={0.01}
            value={glass[slider.key]}
            aria-label={slider.label}
            aria-valuetext={percent(glass[slider.key])}
            onChange={(e) => slide(slider.key, Number(e.target.value))}
          />
          <div className="flex justify-between text-[0.65rem] text-text-2">
            <span>{slider.low}</span>
            <span>{slider.high}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function GlassTuner() {
  return (
    <div id={GLASS_TUNER} popover="auto" className="tuner panel" aria-label="Glass">
      <GlassSliders />
    </div>
  );
}
