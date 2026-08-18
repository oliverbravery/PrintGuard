import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const PROBE = `
plugin.render((ctx) => ({
  type: "col",
  children: [
    { type: "text", value: "origin:" + String(window.origin) },
    { type: "text", value: "fetch:" + typeof fetch },
    { type: "text", value: "socket:" + typeof WebSocket },
    { type: "text", value: "storage:" + (() => { try { return typeof localStorage; } catch { return "blocked"; } })() },
    { type: "text", value: "parent:" + (() => { try { return String(parent.document.title); } catch { return "blocked"; } })() },
    { type: "text", value: "monitors:" + (ctx.state.monitors || []).length },
  ],
}));
`;

async function runInSandbox(page: import("@playwright/test").Page, code: string, state: unknown = {}) {
  return page.evaluate(
    ([code, state]) =>
      new Promise<any>((resolve, reject) => {
        const frame = document.createElement("iframe");
        frame.src = "plugin-sandbox.html";
        frame.sandbox.add("allow-scripts");
        frame.allow = "";
        const answer = (event: MessageEvent) => {
          if (event.source !== frame.contentWindow) return;
          if (event.data.t === "booted") {
            frame.contentWindow!.postMessage({ id: 1, t: "init", code, store: {} }, "*");
          } else if (event.data.t === "ready") {
            frame.contentWindow!.postMessage({ id: 2, t: "state", state }, "*");
          } else {
            removeEventListener("message", answer);
            resolve(event.data);
          }
        };
        addEventListener("message", answer);
        document.body.appendChild(frame);
        setTimeout(() => reject(new Error("sandbox never answered")), 5000);
      }),
    [code, state] as const,
  );
}

test("a plugin runs in an opaque origin with no way out", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(page, PROBE, { monitors: [{ id: "a" }, { id: "b" }] });
  const said = Object.fromEntries(result.tree.children.map((c: any) => c.value.split(":")));

  expect(said.origin).toBe("null");
  expect(said.fetch).toBe("undefined");
  expect(said.socket).toBe("undefined");
  expect(said.storage).toBe("blocked");
  expect(said.parent).toBe("blocked");
  expect(said.monitors).toBe("2");
});

test("a plugin that throws is reported rather than silently dead", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(page, "plugin.render(() => { throw new Error('boom'); });");

  expect(result.t).toBe("failed");
  expect(result.message).toContain("boom");
});

test("effects come back for the host to check rather than being performed", async ({ page }) => {
  await page.goto("/");
  const result = await runInSandbox(
    page,
    "plugin.render((ctx) => { ctx.command({ cmd: 'printer.action', action: 'cancel' }); return { type: 'text', value: 'hi' }; });",
  );

  expect(result.effects).toEqual([{ kind: "command", cmd: { cmd: "printer.action", action: "cancel" } }]);
});

test("code only runs when it came from the frame's host", async ({ page }) => {
  await page.goto("/");
  const result = await page.evaluate(
    () =>
      new Promise<any>((resolve, reject) => {
        const frame = document.createElement("iframe");
        frame.src = "plugin-sandbox.html";
        frame.sandbox.add("allow-scripts");
        const bystander = document.createElement("iframe");
        const said: string[] = [];
        const answer = (event: MessageEvent) => {
          if (event.source !== frame.contentWindow) return;
          said.push(event.data.t);
          if (event.data.t === "booted") {
            const code = "plugin.render(() => ({ type: 'text', value: 'installed' }));";
            frame.contentWindow!.postMessage({ id: 1, t: "init", code, store: {} }, "*");
          } else if (event.data.t === "ready") {
            const script = bystander.contentDocument!.createElement("script");
            script.textContent =
              "const hijack = { id: 2, t: 'init', code: \"plugin.render(() => ({ type: 'text', value: 'hijacked' }));\" };" +
              "for (let i = 0; i < parent.frames.length; i++) parent.frames[i].postMessage(hijack, '*');";
            bystander.contentDocument!.body.appendChild(script);
            setTimeout(() => frame.contentWindow!.postMessage({ id: 3, t: "state", state: {} }, "*"), 100);
          } else if (event.data.id === 3) {
            removeEventListener("message", answer);
            resolve({ ...event.data, said });
          }
        };
        addEventListener("message", answer);
        document.body.appendChild(frame);
        document.body.appendChild(bystander);
        setTimeout(() => reject(new Error("sandbox never answered")), 5000);
      }),
  );

  expect(result.tree.value).toBe("installed");
  expect(result.said.filter((t: string) => t === "ready")).toHaveLength(1);
});

const PIP = `
plugin.action((name, arg, ctx) => {
  if (name === "toggle") ctx.store.picked = [arg];
});
plugin.render((ctx) => ({
  type: "col",
  children: [
    { type: "row", children: (ctx.state.cameras || []).map((c) => ({ type: "button", label: c.name, action: "toggle", arg: c.id })) },
    { type: "camera", camera_id: (ctx.store.picked || ["c1"])[0] },
  ],
}));
`;

const PLUGIN = {
  id: "pip",
  manifest: {
    id: "pip", name: "Picture in picture", version: "1.0.0", description: "", author: "", homepage: "",
    permissions: ["state:read", "camera:view"], surfaces: ["panel", "float"], hosts: [], events: [], tick_s: 0,
  },
  files: ["plugin.js"],
  digests: {},
  source: { kind: "github", repo: "oliverbravery/PrintGuard", ref: "abc1234" },
  granted: ["state:read", "camera:view"],
  config: {},
  verified: true,
  enabled: true,
  installed: 0,
  failure: null,
};

const MONITOR_PIP = `
plugin.action((name, arg, ctx) => {
  if (name !== "float") return;
  ctx.store.picked = arg;
  ctx.float(true);
});
plugin.render((ctx) => {
  if (!ctx.target) return { type: "camera", camera_id: ctx.store.picked };
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  return { type: "button", label: "Float " + monitor.name, action: "float", arg: monitor.camera_id };
});
`;

const MONITOR = {
  id: "m1", name: "Bench", camera_id: "c1", printer_id: "", enabled: true, threshold: 0.6, sensitivity: 1,
  consecutive: 3, notify: true, on_defect: "pause", cooldown_s: 30, alert: null, watching: true, result: null,
};

const PERMISSIONS = [
  { id: "state:read", label: "Read", description: "", fields: { cameras: ["id", "name", "online"], monitors: ["id", "name", "camera_id", "alert"] } },
  { id: "camera:view", label: "Cameras", description: "" },
  { id: "printer:control", label: "Control printers", description: "", commands: ["printer.action"] },
];

async function dashboardWithPlugin(
  page: import("@playwright/test").Page,
  code: string,
  granted = PLUGIN.granted,
  surfaces = PLUGIN.manifest.surfaces,
  assets: Record<string, string> = {},
) {
  await page.addInitScript(() => {
    class Offline extends EventTarget {
      readyState = 0;
      send(): void {}
      close(): void {}
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = Offline;
  });
  await page.goto("/");
  await page.evaluate(
    ({ plugin, permissions, code, granted, surfaces, monitor, assets }) => {
      const win = window as any;
      const sent: any[] = [];
      win.__sent = sent;
      win.__pg.setState({
        mode: "hub",
        phase: "ready",
        link: { send: (cmd: any) => sent.push(cmd), close() {} },
        engine: {
          mode: "hub", version: "test", update: null,
          cameras: [
            {
              id: "c1", name: "Workshop", source: { kind: "rtsp", url: "rtsp://camera" }, printer_id: null,
              max_fps: 30, brightness: 1, contrast: 1, sharpness: 0, crop: null, rotation: 0,
              target_fps: 30, achieved_fps: 29.8, inferring: false, in_use: true, online: true, standby: false, last_result: null,
            },
          ],
          printers: [], monitors: [monitor], tokens: [], integrations: [], notifiers: [],
          settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {} },
          stats: { inference_device: "CPU", infer_ms: 1, capacity_fps: 1 },
          plugins: [{ ...plugin, manifest: { ...plugin.manifest, surfaces }, granted }],
          plugin_permissions: permissions,
          plugin_events: { state: [] },
          plugin_assets: { png: "image/png", txt: "text/plain", mp3: "audio/mpeg" },
          plugin_host: true,
        },
      });
      win.__pgEvent({ event: "state", ...win.__pg.getState().engine });
      const request = sent.find((c) => c.cmd === "plugin.code");
      win.__pgEvent({ event: "plugin_code", id: "pip", sources: { "plugin.js": code }, assets, req_id: request?.req_id });
    },
    { plugin: PLUGIN, permissions: PERMISSIONS, code, granted, surfaces, monitor: MONITOR, assets },
  );
  await expect.poll(() => page.evaluate(() => Object.keys((window as any).__pg.getState().pluginTrees).length)).toBeGreaterThan(0);
}

test("an installed plugin draws its panel with a real camera feed", async ({ page }) => {
  await dashboardWithPlugin(page, PIP);

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await expect(panel.getByRole("button", { name: "Workshop" })).toBeVisible();
  await expect(panel.locator("video")).toBeAttached();
  await expect(panel.getByText("verified")).toBeVisible();
});

test("a camera node is refused when the feed permission is not granted", async ({ page }) => {
  await dashboardWithPlugin(page, PIP, ["state:read"]);

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await expect(panel.getByText("Camera feeds not permitted")).toBeVisible();
  await expect(panel.locator("video")).toHaveCount(0);
});

test("a command the plugin was not granted never reaches the engine", async ({ page }) => {
  await dashboardWithPlugin(
    page,
    "plugin.render((ctx) => { ctx.command({ cmd: 'printer.action', id: 'p1', action: 'cancel' }); return { type: 'text', value: 'drawn' }; });",
  );

  await expect(page.getByText("drawn")).toBeVisible();
  const sent = await page.evaluate(() => (window as any).__sent.map((c: any) => c.cmd));
  expect(sent).not.toContain("printer.action");
  await expect(page.getByText("without permission")).toBeVisible();
});

test("a monitor surface puts a pop-out button on each monitor and nothing on the dashboard", async ({ page }) => {
  await dashboardWithPlugin(page, MONITOR_PIP, PLUGIN.granted, ["monitor", "float"]);
  test.skip(!(await page.evaluate(() => "documentPictureInPicture" in window)), "no Document Picture-in-Picture here");

  await expect(page.locator("section", { hasText: "Picture in picture" })).toHaveCount(0);
  await page.getByRole("button", { name: "Float Bench" }).click();

  await expect
    .poll(() =>
      page.evaluate(() => {
        const pip = (window as any).documentPictureInPicture.window;
        return pip ? pip.document.querySelectorAll("video").length : 0;
      }),
    )
    .toBe(1);

  const spare = await page.evaluate(() => {
    const pip = (window as any).documentPictureInPicture.window;
    const feed = pip.document.querySelector("video").parentElement.getBoundingClientRect().height;
    return pip.document.body.getBoundingClientRect().height - feed;
  });

  expect(spare).toBeLessThanOrEqual(2);
});

async function silentAudio(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const win = window as any;
    win.__tones = 0;
    win.AudioContext = class {
      currentTime = 0;
      destination = {};
      resume() {}
      createGain() {
        return { gain: { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (node: any) => node };
      }
      createOscillator() {
        win.__tones += 1;
        return { type: "", frequency: { setValueAtTime() {} }, connect: (node: any) => node, start() {}, stop() {} };
      }
    };
  });
}

const NOISY = "plugin.render((ctx) => { ctx.sound([{ hz: 880, ms: 100 }]); return { type: 'text', value: 'drawn' }; });";

test("a sound plays for a plugin granted it", async ({ page }) => {
  await silentAudio(page);
  await dashboardWithPlugin(page, NOISY, ["sound"]);

  await expect(page.getByText("drawn")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__tones)).toBeGreaterThan(0);
});

test("a sound stays quiet for a plugin that was not granted it", async ({ page }) => {
  await silentAudio(page);
  await dashboardWithPlugin(page, NOISY, ["state:read"]);

  await expect(page.getByText("drawn")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__tones)).toBe(0);
});

const SOUNDS = readFileSync(new URL("../../plugins/alert-sounds/plugin.js", import.meta.url), "utf8");

test("the sounds plugin stays quiet until a monitor is switched on and a fresh alert lands", async ({ page }) => {
  await silentAudio(page);
  await dashboardWithPlugin(page, SOUNDS, ["state:read", "sound"], ["monitor", "panel"]);

  const tile = page.locator("article", { hasText: "Bench" });
  await tile.getByRole("button", { name: "🔇" }).click();
  await expect(tile.getByRole("button", { name: "🔊" })).toBeVisible();
  await expect(page.getByText("Sounding for Bench")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__tones)).toBe(0);

  await page.evaluate(() => {
    const win = window as any;
    const engine = win.__pg.getState().engine;
    win.__pgEvent({ event: "state", ...engine, monitors: engine.monitors.map((m: any) => ({ ...m, alert: { ts: 123, score: 0.9, action: "pause" } })) });
  });

  await expect.poll(() => page.evaluate(() => (window as any).__tones)).toBeGreaterThan(0);
});

const FIELDS = `
plugin.action((name, arg, ctx) => { ctx.store[name] = arg; });
plugin.render((ctx) => ({
  type: "col",
  children: [
    { type: "input", label: "Webhook", action: "url", value: ctx.store.url || "", placeholder: "https://" },
    { type: "toggle", label: "Loud", action: "loud", on: ctx.store.loud === true },
    { type: "image", asset: "icon.png", label: "Logo" },
    { type: "text", value: "url:" + (ctx.store.url || "") + " loud:" + (ctx.store.loud === true) + " read:" + (ctx.assets["notes.txt"] || "") },
  ],
}));
`;

test("a plugin takes input and shows the files it shipped", async ({ page }) => {
  const PNG =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  await dashboardWithPlugin(page, FIELDS, ["state:read"], ["panel"], {
    "icon.png": PNG,
    "notes.txt": btoa("hello"),
  });

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await panel.getByLabel("Webhook").fill("https://hooks.example.com/x");
  await panel.getByLabel("Webhook").blur();
  await panel.getByLabel("Loud").click();

  await expect(panel.getByText("url:https://hooks.example.com/x loud:true read:hello")).toBeVisible();
  await expect(panel.getByAltText("Logo")).toHaveJSProperty("naturalWidth", 1);
});

test("pop-out puts the panel in a picture-in-picture window, themed", async ({ page }) => {
  await dashboardWithPlugin(page, PIP);
  test.skip(!(await page.evaluate(() => "documentPictureInPicture" in window)), "no Document Picture-in-Picture here");

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await panel.getByRole("button", { name: /Pop out/ }).click();
  await expect(panel.getByText("Showing in a floating window")).toBeVisible();

  const inside = await page.evaluate(() => {
    const pip = (window as any).documentPictureInPicture.window;
    return {
      theme: pip.document.documentElement.dataset.theme,
      styles: pip.document.querySelectorAll('style, link[rel="stylesheet"]').length,
      videos: pip.document.querySelectorAll("video").length,
      buttons: [...pip.document.querySelectorAll("button")].length,
    };
  });

  expect(inside.videos).toBe(1);
  expect(inside.buttons).toBe(1);
  expect(inside.styles).toBeGreaterThan(0);
  expect(inside.theme).toBeTruthy();
});
