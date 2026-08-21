import type { CustomTheme, Glass, ThemeBase, ThemeTokenKey } from "./types";

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

export const PALETTES: Record<ThemeBase, Palette> = {
  dark: {
    ink0: "#0b0c0a", ink1: "#11130e", ink2: "#181b13", ink3: "#20241a",
    line0: "#262b20", line1: "#39402f",
    text0: "#eceee6", text1: "#a8af9c", text2: "#7e866d",
    accent: "#ff4d00", ok: "#8ac926", warn: "#ffb000", bad: "#ff3b30",
  },
  light: {
    ink0: "#e7e8e0", ink1: "#f2f3ec", ink2: "#fbfcf6", ink3: "#dfe1d6",
    line0: "#d3d5c8", line1: "#c2c5b4",
    text0: "#1b1d16", text1: "#4a4f40", text2: "#646959",
    accent: "#bc3809", ok: "#487212", warn: "#8d5d00", bad: "#c42920",
  },
};

const STORAGE_KEY = "pg.theme";
export const GLASS = "glass";
export const GLASS_DEFAULT: Glass = { opacity: 0.38, tone: 0.08 };
const PREFERRED_MUTED = 0.85;
const AA = 4.5;
const BACKDROP_CELLS = 8;
const SATURATION_HEADROOM = 0.05;
const MEDIA = "(prefers-color-scheme: dark)";

interface Resolved {
  base: ThemeBase;
  colors: Palette | null;
}

function grey(level: number): number {
  return level <= 0.03928 ? level / 12.92 : ((level + 0.055) / 1.055) ** 2.4;
}

function levelOf(luminance: number): number {
  return luminance <= 0.0031308 ? luminance * 12.92 : 1.055 * luminance ** (1 / 2.4) - 0.055;
}

function mutedRatio(level: number, ink: number, alpha: number): number {
  const muted = grey(ink * alpha + level * (1 - alpha));
  const surface = grey(level);
  return (Math.max(muted, surface) + 0.05) / (Math.min(muted, surface) + 0.05);
}

function boundary(ink: number, alpha: number): number {
  let low = 0;
  let high = 1;
  for (let step = 0; step < 24; step += 1) {
    const mid = (low + high) / 2;
    if ((mutedRatio(mid, ink, alpha) >= AA) === (ink < 0.5)) high = mid;
    else low = mid;
  }
  return ink < 0.5 ? high : low;
}

function mutedAlpha(level: number, ink: number): number {
  let low = PREFERRED_MUTED;
  let high = 1;
  if (mutedRatio(level, ink, low) >= AA) return low;
  for (let step = 0; step < 24; step += 1) {
    const mid = (low + high) / 2;
    if (mutedRatio(level, ink, mid) >= AA) high = mid;
    else low = mid;
  }
  return high;
}

const LIGHTEST_UNDER_WHITE_INK = boundary(1, 1);
const DARKEST_UNDER_BLACK_INK = boundary(0, 1);

let cover: { lo: number; hi: number } | null = null;

export function litGlass(tone: number): boolean {
  return tone >= DARKEST_UNDER_BLACK_INK;
}

function behindTheGlass(tone: number): { lo: number; hi: number } {
  const page = levelOf(luminance(PALETTES[litGlass(tone) ? "light" : "dark"].ink0));
  return {
    lo: Math.min(cover ? cover.lo : page, tone),
    hi: Math.min(1, Math.max(cover ? cover.hi : page, tone) + SATURATION_HEADROOM),
  };
}

function readableAt(tint: number, tone: number): boolean {
  const { lo, hi } = behindTheGlass(tone);
  return litGlass(tone)
    ? tint * tone + (1 - tint) * lo >= DARKEST_UNDER_BLACK_INK
    : tint * tone + (1 - tint) * hi <= LIGHTEST_UNDER_WHITE_INK;
}

export function clearestTint(tone: number): number {
  if (readableAt(0, tone)) return 0;
  let low = 0;
  let high = 1;
  for (let step = 0; step < 16; step += 1) {
    const mid = (low + high) / 2;
    if (readableAt(mid, tone)) high = mid;
    else low = mid;
  }
  return high;
}

export function glassMaterial({ opacity, tone }: Glass): { lit: boolean; vars: Record<string, string> } {
  const lit = litGlass(tone);
  const floor = clearestTint(tone);
  const settled = floor + opacity * (1 - floor);
  const { lo, hi } = behindTheGlass(tone);
  const alpha = mutedAlpha(settled * tone + (1 - settled) * (lit ? lo : hi), lit ? 0 : 1);
  const level = Math.round(tone * 255);
  const channels = lit ? "0 0 0" : "255 255 255";
  return {
    lit,
    vars: {
      "--glass-surface": `rgb(${level} ${level} ${level} / ${settled.toFixed(3)})`,
      "--glass-ink": `rgb(${channels})`,
      "--glass-muted": `rgb(${channels} / ${alpha.toFixed(3)})`,
      "--glass-contrast": lit ? "rgb(255 255 255)" : "rgb(0 0 0)",
    },
  };
}

export async function measureCover(src: string | null): Promise<void> {
  if (!src) cover = null;
  else {
    const picture = new Image();
    picture.src = src;
    await picture.decode();
    const canvas = document.createElement("canvas");
    canvas.width = BACKDROP_CELLS;
    canvas.height = BACKDROP_CELLS;
    const paper = canvas.getContext("2d", { willReadFrequently: true })!;
    paper.drawImage(picture, 0, 0, BACKDROP_CELLS, BACKDROP_CELLS);
    const { data } = paper.getImageData(0, 0, BACKDROP_CELLS, BACKDROP_CELLS);
    let lo = 1;
    let hi = 0;
    for (let at = 0; at < data.length; at += 4) {
      const level = levelOf(
        0.2126 * grey(data[at] / 255) + 0.7152 * grey(data[at + 1] / 255) + 0.0722 * grey(data[at + 2] / 255),
      );
      lo = Math.min(lo, level);
      hi = Math.max(hi, level);
    }
    cover = { lo, hi };
  }
  applyTheme(current.themeId, current.themes, current.glass);
}

export function resolveTheme(themeId: string, themes: CustomTheme[], glass: Glass = GLASS_DEFAULT): Resolved {
  const custom = themes.find((t) => t.id === themeId);
  if (custom) return { base: custom.base, colors: { ...PALETTES[custom.base], ...custom.colors } };
  if (themeId === "light" || themeId === "dark") return { base: themeId, colors: null };
  if (themeId === GLASS) return { base: litGlass(glass.tone) ? "light" : "dark", colors: null };
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

function readableOn(hex: string): string {
  return luminance(hex) > 0.42 ? "#0b0c0a" : "#f3f4ed";
}

let current: { themeId: string; themes: CustomTheme[]; glass: Glass } = { themeId: "system", themes: [], glass: GLASS_DEFAULT };
let previewing = false;

export function beginPreview(): void {
  previewing = true;
}
export function endPreview(): void {
  previewing = false;
}

export function applyTheme(themeId: string, themes: CustomTheme[], given?: Partial<Glass>, force = false): void {
  if (previewing && !force) return;
  const glass = { ...GLASS_DEFAULT, ...given };
  current = { themeId, themes, glass };
  const { base, colors } = resolveTheme(themeId, themes, glass);
  const material = glassMaterial(glass).vars;
  const glassy = themeId === GLASS;
  const root = document.documentElement;
  root.dataset.theme = base;
  root.style.colorScheme = base;
  root.toggleAttribute("data-glass", glassy);
  for (const t of TOKENS) {
    if (colors) root.style.setProperty(t.cssVar, colors[t.key]);
    else root.style.removeProperty(t.cssVar);
  }
  if (colors) root.style.setProperty("--color-on-accent", readableOn(colors.accent));
  else root.style.removeProperty("--color-on-accent");
  for (const [name, value] of Object.entries(material)) {
    if (glassy) root.style.setProperty(name, value);
    else root.style.removeProperty(name);
  }
  const bg = colors ? colors.ink0 : PALETTES[base].ink0;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  if (previewing) return;
  const vars = colors
    ? { ...Object.fromEntries(TOKENS.map((t) => [t.cssVar, colors[t.key]])), "--color-on-accent": readableOn(colors.accent) }
    : glassy
      ? material
      : null;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: themeId, base, vars, bg, glass: glassy }));
}

window.matchMedia(MEDIA).addEventListener("change", () => {
  if (current.themeId === "system") applyTheme(current.themeId, current.themes, current.glass);
});

const ORDER = ["system", "light", "dark", GLASS] as const;

export function nextScheme(themeId: string): string {
  const i = ORDER.indexOf(themeId as (typeof ORDER)[number]);
  return ORDER[(i + 1) % ORDER.length];
}
