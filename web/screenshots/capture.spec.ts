import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test, type Browser, type Locator, type Page } from "@playwright/test";
import type { Camera, EngineState, Monitor, Printer, ScorePoint } from "../src/types";

const here = dirname(fileURLToPath(import.meta.url));
const asset = (name: string) => resolve(here, "../../docs/assets", name);
const guideShot = (name: string) => resolve(here, "../public/guide", name);
const dataUrl = (name: string) => `data:image/jpeg;base64,${readFileSync(resolve(here, "frames", name)).toString("base64")}`;
const FRAMES = { healthy: dataUrl("healthy.jpg"), defect: dataUrl("defect.jpg") };
const VERSION = readFileSync(resolve(here, "../../pyproject.toml"), "utf8").match(/^version = "(.+)"$/m)![1];

const NOW = 1_700_000_000_000;
const series = (fn: (i: number) => number, n = 48): ScorePoint[] =>
  Array.from({ length: n }, (_, i) => ({ ts: NOW - (n - i) * 1500, score: Math.min(1, Math.max(0, fn(i))) }));

const camera = (id: string, name: string, source: Camera["source"], inferring = false): Camera => ({
  id, name, source, printer_id: null, max_fps: 30, brightness: 1, contrast: 1, sharpness: 0,
  crop: null, rotation: 0, target_fps: 30, achieved_fps: 29.8, inferring, in_use: true, online: true, last_result: null,
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
    mode: "hub",
    host: "docker", version: VERSION, update: null,
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
    settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {}, inference_runtime: "auto", catalogue_url: "" },
    tokens: [], stats: { inference_device: "CPU", infer_ms: 18, capacity_fps: 1783 }, integrations: [], notifiers: [],
    plugins: [], plugin_permissions: PERMISSIONS, plugin_events: {}, plugin_platforms: PLATFORMS, plugin_host: true,
    plugin_event_permissions: { state: "state:read", frame: "camera:frames", history: "history:read" },
  };
}

const PLATFORMS = {
  docker: "Docker", "docker-nvidia": "NVIDIA image", "docker-intel": "Intel image",
  macos: "macOS", windows: "Windows", browser: "Browser",
};

const PERMISSIONS = [
  {
    id: "state:read", label: "Read the dashboard",
    description: "Monitor names, scores and alerts, camera and printer status.",
    fields: {
      monitors: ["id", "name", "camera_id", "printer_id", "enabled", "watching", "threshold", "result", "alert"],
      cameras: ["id", "name", "online", "standby", "in_use", "max_fps", "achieved_fps"],
      printers: ["id", "name", "provider", "online", "device_state"],
    },
  },
  { id: "camera:view", label: "Show live camera feeds", description: "Show a live feed in its panel." },
  { id: "notify", label: "Show notifications", description: "Show a message in the dashboard." },
  { id: "sound", label: "Play a sound", description: "Play a sound on this device." },
  { id: "alert:send", label: "Use your alert channels", description: "Send through your ntfy, Telegram or Discord." },
  { id: "net", label: "Reach the internet", description: "Reach the addresses it lists.", urls: true },
  { id: "oauth", label: "Connect an account", description: "Sign you in to a service. PrintGuard holds the tokens.", risky: true },
  { id: "background", label: "Paint the dashboard's background", description: "Put a picture behind the dashboard." },
];

const CATALOGUE = [
  {
    id: "picture-in-picture", name: "Picture in picture", version: "1.2.0", author: "oliverbravery",
    description: "Puts a pop-out button on every monitor that floats its camera above your other windows.",
    icon: "icon.png", media: ["shots/monitor.png"],
    repo: "oliverbravery/PrintGuard", path: "plugins/picture-in-picture", ref: "a".repeat(40),
    permissions: ["state:read", "camera:view"], platforms: [], surfaces: ["monitor", "float"], digests: {},
  },
  {
    id: "alert-sounds", name: "Alert sounds", version: "1.1.0", author: "oliverbravery",
    description: "Sounds a horn, a bell or an alarm the moment a defect is caught, on the monitors you switch it on for.",
    icon: "icon.png", media: ["shots/settings.png"],
    repo: "oliverbravery/PrintGuard", path: "plugins/alert-sounds", ref: "c".repeat(40),
    permissions: ["state:read", "sound"], platforms: [], surfaces: ["settings"], digests: {},
  },
  {
    id: "progress-reports", name: "Progress reports", version: "1.0.0", author: "oliverbravery",
    description: "Sends how far a print has got and how many defects it has seen, as often as you ask, on the monitors you switch it on for.",
    icon: "icon.png", media: ["shots/settings.png"],
    repo: "oliverbravery/PrintGuard", path: "plugins/progress-reports", ref: "d".repeat(40),
    permissions: ["state:read", "alert:send"], platforms: [], surfaces: ["settings"], digests: {},
  },
  {
    id: "spotify", name: "Spotify", version: "1.0.0", author: "oliverbravery",
    description: "Puts the current cover behind the dashboard, with the track and the transport in a panel.",
    icon: "icon.png", media: ["shots/dashboard.jpg"],
    repo: "oliverbravery/PrintGuard", path: "plugins/spotify", ref: "e".repeat(40),
    permissions: ["net", "oauth", "background"], platforms: [], surfaces: ["panel"], digests: {},
  },
];

const NOW_PLAYING = {
  item: {
    name: "Test Pattern",
    artists: [{ name: "Bench Radio" }],
    album: { images: [{ url: "https://i.scdn.co/image/cover" }] },
  },
  is_playing: true,
};

function installed(id: string, name: string, permissions: string[], surfaces: string[], files: string[]) {
  return {
    id,
    manifest: {
      id, name, version: "1.0.0", description: "", author: "oliverbravery", homepage: "",
      icon: "icon.png", media: [],
      permissions, reasons: {}, surfaces, platforms: [], assets: [], urls: [],
      secrets: {}, provides: {}, consumes: [], oauth: {}, events: files.includes("panel.html") ? ["http"] : [], tick_s: 0,
    },
    files,
    digests: {},
    source: { kind: "github", repo: "oliverbravery/PrintGuard", path: `plugins/${id}`, ref: "a".repeat(40) },
    granted: permissions,
    config: {},
    secrets_set: ["oauth", "oauth_client_id"],
    verified: true,
    enabled: true,
    installed: NOW / 1000,
    failure: null,
  };
}

const INSTALLED = {
  id: "picture-in-picture",
  manifest: {
    id: "picture-in-picture", name: "Picture in picture", version: "1.2.0", author: "oliverbravery", homepage: "",
    icon: "icon.png", media: ["shots/monitor.png"],
    description: "Puts a pop-out button on every monitor that floats its camera above your other windows.",
    permissions: ["state:read", "camera:view"], reasons: {}, surfaces: ["monitor"], platforms: [], assets: [],
    urls: [], secrets: {}, provides: {}, consumes: [], oauth: {}, events: [], tick_s: 0,
  },
  files: ["plugin.js"], digests: {},
  source: { kind: "github", repo: "oliverbravery/PrintGuard", path: "plugins/picture-in-picture", ref: "a".repeat(40) },
  granted: ["state:read", "camera:view"], config: {}, secrets_set: [], verified: true, enabled: true, installed: NOW / 1000, failure: null,
}

interface Crop extends Omit<Scene, "name" | "theme"> {
  id: string;
  target: (page: Page) => Locator;
  pad?: number;
  tallest?: number;
}

interface Scene {
  name: string;
  plugins?: string[];
  width: number;
  height: number;
  theme: "dark" | "light";
  detailId?: string;
  customising?: boolean;
  settingsTab?: string;
  dialog?: string;
  history?: Record<string, ScorePoint[]>;
  hideFeeds?: boolean;
  catalogue?: unknown[];
  prepare?: (page: Page) => Promise<void>;
  tuner?: boolean;
  mutate?: (engine: EngineState) => void;
}

const live = (e: EngineState) => {
  e.plugin_events = { http: ["tag", "status", "body"] };
  e.settings.theme = "glass";
  e.monitors = e.monitors.slice(0, 2);
  e.plugins = [
    installed("spotify", "Spotify", ["net", "oauth", "background"], ["panel"], ["panel.html"]),
    installed("picture-in-picture", "Picture in picture", ["state:read", "camera:view"], ["monitor"], ["plugin.js"]),
  ] as never;
};

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
  {
    name: "plugins", width: 1360, height: 860, theme: "dark", settingsTab: "plugins", catalogue: CATALOGUE,
    mutate: (e) => {
      e.plugins = [INSTALLED as never];
    },
  },
  {
    name: "plugin-page", width: 1360, height: 900, theme: "dark", settingsTab: "plugins", catalogue: CATALOGUE,
    prepare: async (page) => {
      await page.locator('[role="button"]', { hasText: "Spotify" }).first().click();
      await page.waitForTimeout(700);
      await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
    },
  },
  { name: "plugins-live", width: 1360, height: 720, theme: "dark", plugins: ["spotify", "picture-in-picture"], mutate: live },
  { name: "glass", width: 1360, height: 720, theme: "dark", plugins: ["spotify", "picture-in-picture"], tuner: true, mutate: live },
];

const surfaces = (e: EngineState) => {
  e.plugins = [
    installed("alert-sounds", "Alert sounds", ["state:read", "sound"], ["settings"], ["plugin.js"]),
    installed("progress-reports", "Progress reports", ["state:read", "alert:send"], ["settings"], ["plugin.js", "worker.js"]),
  ] as never;
};

const stoodDown = (e: EngineState) => {
  e.monitors = [
    { ...e.monitors[1], alert: null, watching: true },
    { ...e.monitors[2], name: "Ender 3 V3", printer_id: "p2", watching: false },
  ];
  e.printers[1] = { ...e.printers[1], device_state: { status: "idle", progress: 0, job: null } };
  e.cameras[2] = { ...e.cameras[2], name: "Garage - Ender", inferring: false, target_fps: 0, achieved_fps: 0, in_use: false };
};

const NOTIFIERS = [
  {
    id: "ntfy", label: "ntfy", docs_url: "",
    schema: { properties: { url: { type: "string", title: "Topic URL", placeholder: "https://ntfy.sh/my-prints" } }, required: ["url"] },
  },
  {
    id: "pushover", label: "Pushover", docs_url: "",
    schema: { properties: { api_token: { type: "string", title: "Application API token", secret: true }, user_key: { type: "string", title: "User key", secret: true } }, required: ["api_token", "user_key"] },
  },
  {
    id: "telegram", label: "Telegram", docs_url: "",
    schema: { properties: { token: { type: "string", title: "Bot token", secret: true }, chat_id: { type: "string", title: "Chat ID" } }, required: ["token", "chat_id"] },
  },
  { id: "discord", label: "Discord", docs_url: "", schema: { properties: { webhook: { type: "string", title: "Webhook URL" } }, required: ["webhook"] } },
];

const DESK = { width: 1000, height: 820 } as const;

const CROPS: Crop[] = [
  {
    id: "alert", ...DESK, pad: 0,
    mutate: (e) => {
      e.monitors = e.monitors.slice(0, 2);
    },
    target: (page) => page.locator(".tile-alert"),
  },
  {
    id: "standby", ...DESK, pad: 0, hideFeeds: true, mutate: stoodDown, history: { m3: series(() => 0) },
    target: (page) => page.locator(".tile").nth(1),
  },
  {
    id: "checklist", ...DESK, height: 1000,
    mutate: (e) => {
      e.cameras = [];
      e.printers = [];
      e.monitors = [];
    },
    target: (page) => page.locator(".panel").filter({ hasText: "GET PRINTGUARD WATCHING" }).first(),
  },
  {
    id: "cameras", ...DESK,
    target: (page) => page.locator("section").filter({ hasText: "CAMERA REGISTRY" }).locator(".panel").first(),
  },
  {
    id: "tuning", ...DESK, height: 1500, detailId: "m1",
    target: (page) => page.locator("section").filter({ hasText: "Watch this monitor" }).first(),
  },
  {
    id: "printers", ...DESK, height: 1000, dialog: "printers", pad: 0,
    target: (page) => page.locator("dialog > .panel"),
  },
  {
    id: "alerts", ...DESK, height: 1200, settingsTab: "alerts",
    target: (page) => page.locator("#settings-panel-alerts"),
    mutate: (e) => {
      e.notifiers = NOTIFIERS as never;
      e.settings.notifiers = { ntfy: { url: "https://ntfy.sh/my-prints" } };
    },
  },
  {
    id: "customise", ...DESK, customising: true, pad: 0,
    target: (page) => page.locator(".tile").first(),
  },
  {
    id: "plugins", ...DESK, height: 1600, settingsTab: "plugins", catalogue: CATALOGUE,
    target: (page) => page.locator("#settings-panel-plugins"),
    mutate: (e) => {
      e.plugins = [INSTALLED as never];
    },
  },
];

function pluginSources(id: string): Record<string, string> {
  const dir = resolve(here, "../../plugins", id);
  return Object.fromEntries(
    ["plugin.js", "worker.js", "panel.html"]
      .filter((file) => existsSync(resolve(dir, file)))
      .map((file) => [file, readFileSync(resolve(dir, file), "utf8")]),
  );
}

async function stage(browser: Browser, scene: Scene): Promise<{ page: Page; close: () => Promise<void> }> {
  const built = engine();
  scene.mutate?.(built);
  const context = await browser.newContext({
    viewport: { width: scene.width, height: scene.height },
    deviceScaleFactor: 2,
    colorScheme: scene.theme,
  });
  const page = await context.newPage();
  await page.addInitScript(() => {
    class UnconnectedSocket extends EventTarget {
      readyState = 0;
      send(): void {}
      close(): void {}
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = UnconnectedSocket;
    Object.defineProperty(Document.prototype, "pictureInPictureEnabled", { get: () => true, configurable: true });
  });
  await page.route("https://raw.githubusercontent.com/**", async (route) => {
    const wanted = new URL(route.request().url()).pathname.split("/").slice(4).join("/");
    const local = resolve(here, "../..", wanted);
    if (wanted.startsWith("plugins/") && existsSync(local)) await route.fulfill({ path: local });
    else await route.fulfill({ status: 404, body: "" });
  });
  await page.goto("/");
  await page.evaluate(
    ({ state, theme }) => {
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.colorScheme = theme;
      (window as { __pg: { setState: (s: unknown) => void } }).__pg.setState(state);
    },
    {
      theme: scene.theme,
      state: {
        mode: "hub", phase: "ready", engine: built, history: { ...history, ...scene.history },
        detailId: scene.detailId ?? null, customising: scene.customising ?? false,
        dialog: scene.dialog ?? (scene.settingsTab ? "settings" : null), settingsTab: scene.settingsTab ?? null,
        catalogue: scene.catalogue ?? null,
        ...(scene.plugins ? { link: null } : {}),
      },
    },
  );
  if (scene.plugins) await runPlugins(page, scene.plugins);
  await page.waitForSelector(scene.settingsTab || scene.dialog ? "dialog" : built.monitors.length ? ".aspect-video" : "main");
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}" });
  await page.evaluate((frames) => {
    for (const el of document.querySelectorAll<HTMLElement>(".aspect-video")) {
      const img = document.createElement("img");
      img.src = el.closest(".tile-alert") ? frames.defect : frames.healthy;
      img.style.cssText = "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:3";
      el.appendChild(img);
    }
  }, FRAMES);
  if (scene.tuner) await page.evaluate(() => document.getElementById("glass-tuner")?.showPopover());
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
  await page.waitForTimeout(200);
  return { page, close: () => context.close() };
}

async function capture(browser: Browser, scene: Scene): Promise<void> {
  const { page, close } = await stage(browser, scene);
  if (scene.prepare) await scene.prepare(page);
  await page.screenshot({ path: asset(`${scene.name}.png`) });
  await close();
}

async function captureCrop(browser: Browser, crop: Crop, theme: "dark" | "light"): Promise<void> {
  const { page, close } = await stage(browser, { ...crop, name: crop.id, theme });
  await page.addStyleTag({ content: `*{outline:none!important}${crop.hideFeeds ? ".aspect-video{display:none}" : ""}` });
  const box = (await crop.target(page).boundingBox())!;
  const pad = crop.pad ?? 10;
  await page.screenshot({
    path: guideShot(`${crop.id}-${theme}.jpg`),
    quality: 90,
    clip: {
      x: Math.max(0, box.x - pad),
      y: Math.max(0, box.y - pad),
      width: Math.min(crop.width - Math.max(0, box.x - pad), box.width + pad * 2),
      height: Math.min(crop.height - Math.max(0, box.y - pad), crop.tallest ?? box.height + pad * 2),
    },
  });
  await close();
}

async function runPlugins(page: import("@playwright/test").Page, ids: string[]): Promise<void> {
  const sources = Object.fromEntries(ids.map((id) => [id, pluginSources(id)]));
  await page.evaluate((files) => {
    const win = window as any;
    const sent: any[] = [];
    win.__pg.setState({ link: { send: (cmd: any) => sent.push(cmd), close() {} } });
    win.__pgEvent({ event: "state", ...win.__pg.getState().engine });
    for (const [id, code] of Object.entries(files)) {
      const asked = sent.find((cmd) => cmd.cmd === "plugin.code" && cmd.id === id);
      win.__pgEvent({ event: "plugin_code", id, sources: code, assets: {}, req_id: asked?.req_id });
    }
  }, sources);
  await page.waitForTimeout(600);
  const cover = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 300;
    const paint = canvas.getContext("2d")!;
    const wash = paint.createLinearGradient(0, 0, 300, 300);
    wash.addColorStop(0, "#ff5a1f");
    wash.addColorStop(0.55, "#7b1fa2");
    wash.addColorStop(1, "#0b3b8f");
    paint.fillStyle = wash;
    paint.fillRect(0, 0, 300, 300);
    paint.fillStyle = "rgba(255,255,255,0.16)";
    for (let ring = 0; ring < 5; ring++) {
      paint.beginPath();
      paint.arc(150, 150, 30 + ring * 26, 0, Math.PI * 2);
      paint.lineWidth = 10;
      paint.strokeStyle = "rgba(255,255,255,0.16)";
      paint.stroke();
    }
    return canvas.toDataURL("image/jpeg", 0.9).split(",")[1];
  });
  await page.evaluate(
    ({ playing, art }) => {
      const win = window as any;
      win.__pgEvent({ event: "http", id: "spotify", tag: "player", status: 200, body: playing });
      win.__pgEvent({ event: "http", id: "spotify", tag: "cover", status: 200, body: art });
    },
    { playing: NOW_PLAYING, art: cover },
  );
  await page.waitForTimeout(900);
}

for (const scene of SCENES) {
  test(scene.name, async ({ browser }) => {
    await capture(browser, scene);
  });
}

const pluginShot = (id: string, name: string) => resolve(here, "../../plugins", id, "shots", name);

interface PluginShot {
  id: string;
  file: string;
  scene: Omit<Scene, "name" | "theme">;
  target?: (page: Page) => Locator;
  prepare?: (page: Page) => Promise<void>;
  jpeg?: boolean;
}

const PLUGIN_SHOTS: PluginShot[] = [
  {
    id: "spotify",
    file: "dashboard.jpg",
    jpeg: true,
    scene: { width: 1200, height: 700, plugins: ["spotify", "picture-in-picture"], mutate: live },
  },
  {
    id: "picture-in-picture",
    file: "monitor.png",
    scene: { width: 1200, height: 700, plugins: ["spotify", "picture-in-picture"], mutate: live },
    target: (page) => page.locator(".tile").first(),
  },
  {
    id: "alert-sounds",
    file: "settings.png",
    scene: { width: 1000, height: 1400, detailId: "m1", plugins: ["alert-sounds", "progress-reports"], mutate: surfaces },
    prepare: async (page) => {
      await page.locator("section").filter({ hasText: "Alert sounds" }).getByRole("switch").click();
      await page.waitForTimeout(500);
    },
    target: (page) => page.locator("section").filter({ hasText: "Alert sounds" }).first(),
  },
  {
    id: "progress-reports",
    file: "settings.png",
    scene: { width: 1000, height: 1400, detailId: "m1", plugins: ["alert-sounds", "progress-reports"], mutate: surfaces },
    prepare: async (page) => {
      await page.locator("section").filter({ hasText: "Progress reports" }).getByRole("switch").click();
      await page.waitForTimeout(500);
    },
    target: (page) => page.locator("section").filter({ hasText: "Progress reports" }).first(),
  },
];

async function capturePluginShot(browser: Browser, shot: PluginShot): Promise<void> {
  const { page, close } = await stage(browser, { ...shot.scene, name: `plugin-${shot.id}`, theme: "dark" });
  if (shot.prepare) await shot.prepare(page);
  const kind = shot.jpeg ? ({ type: "jpeg", quality: 88 } as const) : {};
  if (shot.target) await shot.target(page).screenshot({ path: pluginShot(shot.id, shot.file), ...kind });
  else await page.screenshot({ path: pluginShot(shot.id, shot.file), ...kind });
  await close();
}

for (const shot of PLUGIN_SHOTS) {
  test(`plugin shot ${shot.id}`, async ({ browser }) => {
    await capturePluginShot(browser, shot);
  });
}

for (const crop of CROPS) {
  for (const theme of ["dark", "light"] as const) {
    test(`guide ${crop.id} ${theme}`, async ({ browser }) => {
      await captureCrop(browser, crop, theme);
    });
  }
}
