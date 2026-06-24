import type { CustomTheme, ThemeBase, ThemeTokenKey } from "./types";

/** Palette token → its CSS custom property, plus editor grouping/labels. */
interface TokenMeta {
  key: ThemeTokenKey;
  label: string;
  cssVar: string;
}

export const TOKEN_GROUPS: { label: string; tokens: TokenMeta[] }[] = [
  {
    label: "Surfaces",
    tokens: [
      { key: "ink0", label: "Page", cssVar: "--color-ink-0" },
      { key: "ink1", label: "Panel", cssVar: "--color-ink-1" },
      { key: "ink2", label: "Panel top", cssVar: "--color-ink-2" },
      { key: "ink3", label: "Raised", cssVar: "--color-ink-3" },
    ],
  },
  {
    label: "Text",
    tokens: [
      { key: "text0", label: "Primary", cssVar: "--color-text-0" },
      { key: "text1", label: "Secondary", cssVar: "--color-text-1" },
      { key: "text2", label: "Muted", cssVar: "--color-text-2" },
    ],
  },
  {
    label: "Lines",
    tokens: [
      { key: "line0", label: "Hairline", cssVar: "--color-line-0" },
      { key: "line1", label: "Border", cssVar: "--color-line-1" },
    ],
  },
  {
    label: "Status",
    tokens: [
      { key: "accent", label: "Accent", cssVar: "--color-accent" },
      { key: "ok", label: "OK", cssVar: "--color-ok" },
      { key: "warn", label: "Warn", cssVar: "--color-warn" },
      { key: "bad", label: "Bad", cssVar: "--color-bad" },
    ],
  },
];

const TOKENS: TokenMeta[] = TOKEN_GROUPS.flatMap((g) => g.tokens);

export type Palette = Record<ThemeTokenKey, string>;

/** Built-in palettes. The light values mirror the `[data-theme="light"]` block
 *  in styles.css; built-ins render from CSS, so these only seed new custom themes. */
export const PALETTES: Record<ThemeBase, Palette> = {
  dark: {
    ink0: "#0b0c0a", ink1: "#11130e", ink2: "#181b13", ink3: "#20241a",
    line0: "#262b20", line1: "#39402f",
    text0: "#eceee6", text1: "#a8af9c", text2: "#6e755f",
    accent: "#ff4d00", ok: "#8ac926", warn: "#ffb000", bad: "#ff3b30",
  },
  light: {
    ink0: "#e7e8e0", ink1: "#f2f3ec", ink2: "#fbfcf6", ink3: "#dfe1d6",
    line0: "#d3d5c8", line1: "#c2c5b4",
    text0: "#1b1d16", text1: "#4a4f40", text2: "#6b7160",
    accent: "#db410a", ok: "#4f7d14", warn: "#a86f00", bad: "#cf2b22",
  },
};

const STORAGE_KEY = "pg.theme";
const MEDIA = "(prefers-color-scheme: dark)";

interface Resolved {
  base: ThemeBase;
  colors: Palette | null;
}

/** Resolves a theme id to a base scheme and, for custom themes, a full palette. */
export function resolveTheme(themeId: string, themes: CustomTheme[]): Resolved {
  const custom = themes.find((t) => t.id === themeId);
  if (custom) return { base: custom.base, colors: { ...PALETTES[custom.base], ...custom.colors } };
  if (themeId === "light" || themeId === "dark") return { base: themeId, colors: null };
  return { base: window.matchMedia(MEDIA).matches ? "dark" : "light", colors: null };
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

/** A near-black or near-white that stays legible on a saturated fill. */
function readableOn(hex: string): string {
  return luminance(hex) > 0.42 ? "#0b0c0a" : "#f3f4ed";
}

let current: { themeId: string; themes: CustomTheme[] } = { themeId: "system", themes: [] };
let previewing = false;

/** While previewing an unsaved theme, ignore engine-driven applies (which fire on
 *  every state event) so the live edit is not clobbered, and skip the paint cache. */
export function beginPreview(): void {
  previewing = true;
}
export function endPreview(): void {
  previewing = false;
}

/** Applies a theme to the document and caches the resolved snapshot for the
 *  no-flash bootstrap script. The engine setting remains the source of truth.
 *  `force` is used by the editor to apply over an active preview. */
export function applyTheme(themeId: string, themes: CustomTheme[], force = false): void {
  if (previewing && !force) return;
  current = { themeId, themes };
  const { base, colors } = resolveTheme(themeId, themes);
  const root = document.documentElement;
  root.dataset.theme = base;
  root.style.colorScheme = base;
  for (const t of TOKENS) {
    if (colors) root.style.setProperty(t.cssVar, colors[t.key]);
    else root.style.removeProperty(t.cssVar);
  }
  if (colors) root.style.setProperty("--color-on-accent", readableOn(colors.accent));
  else root.style.removeProperty("--color-on-accent");
  const bg = colors ? colors.ink0 : PALETTES[base].ink0;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  if (previewing) return;
  const vars = colors
    ? { ...Object.fromEntries(TOKENS.map((t) => [t.cssVar, colors[t.key]])), "--color-on-accent": readableOn(colors.accent) }
    : null;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: themeId, base, vars, bg }));
}

window.matchMedia(MEDIA).addEventListener("change", () => {
  if (current.themeId === "system") applyTheme(current.themeId, current.themes);
});

const ORDER = ["system", "light", "dark"] as const;

/** Next built-in scheme for the header quick-toggle (custom themes fall to System). */
export function nextScheme(themeId: string): string {
  const i = ORDER.indexOf(themeId as (typeof ORDER)[number]);
  return ORDER[(i + 1) % ORDER.length];
}
