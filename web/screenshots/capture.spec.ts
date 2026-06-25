import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test, type Browser } from "@playwright/test";
import type { Camera, EngineState, Monitor, Printer, ScorePoint } from "../src/types";

const here = dirname(fileURLToPath(import.meta.url));
const asset = (name: string) => resolve(here, "../../docs/assets", name);
const dataUrl = (name: string) => `data:image/jpeg;base64,${readFileSync(resolve(here, "frames", name)).toString("base64")}`;
const FRAMES = { healthy: dataUrl("healthy.jpg"), defect: dataUrl("defect.jpg") };

const NOW = 1_700_000_000_000;
const series = (fn: (i: number) => number, n = 48): ScorePoint[] =>
  Array.from({ length: n }, (_, i) => ({ ts: NOW - (n - i) * 1500, score: Math.min(1, Math.max(0, fn(i))) }));

const camera = (id: string, name: string, source: Camera["source"], inferring = false): Camera => ({
  id, name, source, printer_id: null, max_fps: 30, brightness: 1, contrast: 1, sharpness: 0,
  crop: null, rotation: 0, target_fps: 5, achieved_fps: 4.7, inferring, in_use: true, online: true, last_result: null,
});

const printer = (id: string, name: string, provider: string, status: string, progress: number, job: string): Printer => ({
  id, name, provider, config: {}, online: true, device_state: { status, progress, job },
});

const monitor = (id: string, name: string, camera_id: string, printer_id: string, alerting = false): Monitor => ({
  id, name, camera_id, printer_id, enabled: true, threshold: 0.6, sensitivity: 0.5, consecutive: 3,
  notify: true, on_defect: "pause", cooldown_s: 90, watching: true,
  alert: alerting ? { score: 0.86, action: "pause", ts: NOW } : null,
});

const history: Record<string, ScorePoint[]> = {
  m1: series((i) => 0.1 + 0.05 * Math.sin(i / 3)),
  m2: series((i) => (i < 30 ? 0.12 + 0.03 * Math.sin(i / 3) : 0.12 + (i - 29) * 0.045)),
  m3: series((i) => 0.08 + 0.04 * Math.sin(i / 4 + 1)),
};

function engine(): EngineState {
  return {
    mode: "hub", version: "2.2.0", update: null,
    cameras: [
      camera("c1", "Workshop · Prusa", { kind: "rtsp", url: "rtsp://10.0.0.21:8554/prusa" }, true),
      camera("c2", "Garage · Ender", { kind: "rtsp", url: "rtsp://10.0.0.22:8554/ender" }),
      camera("c3", "Bambu X1C", { kind: "bambu", host: "10.0.0.30" }),
    ],
    printers: [
      printer("p1", "Prusa MK4", "octoprint", "printing", 47, "calibration_cubes.gcode"),
      printer("p2", "Ender 3 V3", "klipper", "paused", 62, "wall_bracket.gcode"),
    ],
    monitors: [
      monitor("m1", "Prusa MK4", "c1", "p1"),
      monitor("m2", "Ender 3 V3", "c2", "p2", true),
      monitor("m3", "Bambu X1C", "c3", ""),
    ],
    settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {} },
    tokens: [], stats: { workers: 4, infer_ms: 18, capacity_fps: 36 }, integrations: [], notifiers: [],
  };
}

interface Scene {
  name: string;
  width: number;
  height: number;
  theme: "dark" | "light";
  detailId?: string;
  customising?: boolean;
  mutate?: (engine: EngineState) => void;
}

const SCENES: Scene[] = [
  { name: "dashboard", width: 1360, height: 620, theme: "dark" },
  { name: "dashboard-light", width: 1360, height: 620, theme: "light" },
  { name: "printer-detail", width: 1360, height: 760, theme: "dark", detailId: "m1" },
  {
    name: "customise", width: 1360, height: 860, theme: "dark", customising: true,
    mutate: (e) => {
      e.settings.layout = {
        monitors: { order: [], pinned: ["m1"], hidden: ["m3"] },
        cameras: { order: [], pinned: [], hidden: ["c3"] },
      };
    },
  },
];

async function capture(browser: Browser, scene: Scene): Promise<void> {
  const built = engine();
  scene.mutate?.(built);
  const context = await browser.newContext({
    viewport: { width: scene.width, height: scene.height },
    deviceScaleFactor: 2,
    colorScheme: scene.theme,
  });
  const page = await context.newPage();
  await page.goto("/");
  await page.evaluate(
    ({ state, theme }) => {
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.colorScheme = theme;
      (window as { __pg: { setState: (s: unknown) => void } }).__pg.setState(state);
    },
    {
      theme: scene.theme,
      state: { mode: "hub", phase: "ready", engine: built, history, detailId: scene.detailId ?? null, customising: scene.customising ?? false },
    },
  );
  await page.waitForSelector(".aspect-video");
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}" });
  await page.evaluate((frames) => {
    for (const el of document.querySelectorAll<HTMLElement>(".aspect-video")) {
      const img = document.createElement("img");
      img.src = el.closest(".tile-alert") ? frames.defect : frames.healthy;
      img.style.cssText = "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1";
      el.appendChild(img);
    }
  }, FRAMES);
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
  await page.waitForTimeout(200);
  await page.screenshot({ path: asset(`${scene.name}.png`) });
  await context.close();
}

for (const scene of SCENES) {
  test(scene.name, async ({ browser }) => {
    await capture(browser, scene);
  });
}
