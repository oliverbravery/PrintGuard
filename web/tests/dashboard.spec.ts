import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import { zipSync } from "fflate";

const EMPTY_ZIP = "UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==";

const camera = (over = {}) => ({
  id: "c1", name: "Workshop", source: { kind: "rtsp", url: "rtsp://camera" }, printer_id: null,
  max_fps: 30, detect_fps: 60, brightness: 1, contrast: 1, sharpness: 0, crop: null, rotation: 0,
  target_fps: 5, achieved_fps: 5, inferring: false, in_use: true, online: true, standby: false, last_result: null, ...over,
});

const monitor = (over = {}) => ({
  id: "m1", name: "Prusa", camera_id: "c1", printer_id: "", enabled: true, threshold: 0.6, consecutive: 3,
  notify: true, on_defect: "pause", cooldown_s: 90, watching: true, alert: null, ...over,
});

const engine = (over = {}) => ({
  version: "test", update: null, cameras: [camera()], printers: [], prints: [], reviews: [], monitors: [monitor()],
  tokens: [], notifiers: [],
  integrations: [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema: { properties: {} } }],
  settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {}, preheat: [] },
  stats: { inference_device: "CPU", infer_ms: 1, capacity_fps: 1 },
  plugins: [], plugin_permissions: [], plugin_events: {}, plugin_assets: {}, ...over,
});

async function dashboard(page: Page, state: Record<string, unknown> = {}) {
  await page.goto("/");
  await page.waitForFunction(() => Boolean((window as any).__pg?.getState().link));
  await page.evaluate(
    (state) => {
      const win = window as any;
      win.__sent = [];
      win.__pg.setState({ phase: "ready", link: { send: (cmd: any) => win.__sent.push(cmd), close() {} }, ...state });
    },
    { engine: engine(), ...state },
  );
}

async function hub(page: Page, onCommand: (command: any, socket: WebSocketRoute) => void = () => {}, state = engine()) {
  const sockets: WebSocketRoute[] = [];
  const commands: any[] = [];
  await page.addInitScript(() => localStorage.setItem("pg.intro.seen", "1"));
  await page.routeWebSocket(/\/api\/ws$/, (socket) => {
    sockets.push(socket);
    socket.onMessage((message) => {
      const command = JSON.parse(String(message));
      commands.push(command);
      onCommand(command, socket);
    });
    socket.send(JSON.stringify({ event: "state", ...state }));
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Prusa" })).toBeVisible();
  return { sockets, commands };
}

const sent = (page: Page, cmd: string) => page.evaluate((cmd) => (window as any).__sent.find((c: any) => c.cmd === cmd), cmd);
const emit = (page: Page, event: Record<string, unknown>) => page.evaluate((event) => (window as any).__pgEvent(event), event);

test("a dropped hub shows in the header, frees its buttons and gets the unsaved edit again", async ({ page }) => {
  const { sockets, commands } = await hub(page);
  const updates = () => commands.filter((c) => c.cmd === "monitor.update");
  await page.evaluate(() => {
    const store = (window as any).__pg.getState();
    store.updateMonitor("m1", { threshold: 0.4 });
    store.flushUpdates();
    store.send({ cmd: "monitor.remove", id: "m1" });
  });
  await expect.poll(() => updates().length).toBe(1);

  await sockets[0].close();
  await expect(page.getByRole("status").getByText("reconnecting")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__pg.getState().isPending("monitor.remove"))).toBe(false);
  await page.evaluate(() => (window as any).__pg.getState().send({ cmd: "monitor.remove", id: "m1" }));
  expect(await page.evaluate(() => (window as any).__pg.getState().isPending("monitor.remove"))).toBe(false);

  await expect.poll(() => updates().length, { timeout: 8000 }).toBe(2);
  await expect(page.getByText("reconnecting")).toBeHidden();
  expect(updates()[1].patch).toEqual({ threshold: 0.4 });
  sockets[1].send(JSON.stringify({ event: "state", ...engine({ monitors: [monitor({ threshold: 0.4 })] }), req_id: updates()[1].req_id }));
  await expect.poll(() => page.evaluate(() => Object.keys((window as any).__pg.getState().optimistic).length)).toBe(0);
});

test("a hub that goes silent without closing is dropped and reached again", async ({ page }) => {
  await page.clock.install();
  const { sockets } = await hub(page);
  await page.evaluate(() => (window as any).__pg.getState().send({ cmd: "monitor.remove", id: "m1" }));
  expect(await page.evaluate(() => (window as any).__pg.getState().isPending("monitor.remove"))).toBe(true);

  await page.clock.fastForward(9_000);
  expect(sockets).toHaveLength(1);
  await sockets[0].send(JSON.stringify({ event: "state", ...engine() }));
  await page.clock.fastForward(9_000);
  expect(await page.evaluate(() => (window as any).__pg.getState().reconnecting)).toBe(false);

  await page.clock.fastForward(2_000);
  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().isPending("monitor.remove"))).toBe(false);
  await page.clock.fastForward(2_000);
  await expect.poll(() => sockets.length).toBe(2);
  await expect(page.getByText("reconnecting")).toBeHidden();
});

test("a command pressed while the hub is away says so and leaves its button free", async ({ page }) => {
  await hub(page);
  await page.evaluate(() => {
    const store = (window as any).__pg.getState();
    store.openDetail("m1");
    store.link.close();
  });
  const panel = page.getByRole("dialog", { name: "Prusa" });
  await panel.getByRole("button", { name: "Delete" }).click();

  await expect(panel.getByRole("status").filter({ hasText: "wasn't sent" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Delete" })).toBeEnabled();
  expect(await page.evaluate(() => (window as any).__pg.getState().pending)).toEqual({});
});

test("deleting a monitor from its panel closes it and brings the other feeds back", async ({ page }) => {
  const cameras = [camera(), camera({ id: "c2", name: "Garage" })];
  const voron = monitor({ id: "m2", name: "Voron", camera_id: "c2" });
  await hub(
    page,
    (command, socket) => {
      if (command.cmd !== "monitor.remove") return;
      socket.send(JSON.stringify({ event: "state", ...engine({ cameras, monitors: [voron] }), req_id: command.req_id }));
    },
    engine({ cameras, monitors: [monitor(), voron] }),
  );
  await page.evaluate(() => (window as any).__pg.getState().openDetail("m1"));
  const panel = page.getByRole("dialog", { name: "Prusa" });
  await expect(panel).toBeVisible();
  const feedRestarted = page.waitForRequest(/\/hls\/c2\//);
  await panel.getByRole("button", { name: "Delete" }).click();

  await expect(panel).toBeHidden();
  await feedRestarted;
  expect(await page.evaluate(() => (window as any).__pg.getState().detailId)).toBeNull();
});

test("a history or review sheet closes when what it shows is removed elsewhere", async ({ page }) => {
  const review = { id: "r1", monitor_id: "m1", status: "ready", started: 1, ended: 2, frames: 0, alerts: 0 };
  await dashboard(page, { engine: engine({ reviews: [review] }), statsMonitorId: "m1", reviewId: "r1" });
  await emit(page, { event: "state", ...engine({ monitors: [] }) });

  expect(await page.evaluate(() => [(window as any).__pg.getState().statsMonitorId, (window as any).__pg.getState().reviewId])).toEqual([null, null]);
});

const review = (over = {}) => ({
  id: "r1", monitor_id: "m1", status: "ready", started: 1, ended: 2, frames: 3, alerts: 1, chosen: 0, sent: 0, code: null, retry_at: null, ...over,
});

test("a tile asks about its last print only", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review(), review({ id: "r2", status: "dismissed" })] }) });
  await expect(page.getByRole("heading", { name: "Prusa" })).toBeVisible();
  await expect(page.getByRole("button", { name: /from the last print/ })).toHaveCount(0);

  await emit(page, { event: "state", ...engine({ reviews: [review({ status: "dismissed" }), review({ id: "r2", frames: 7 })] }) });
  await page.getByRole("button", { name: "Review 7 frames from the last print" }).click();
  expect(await page.evaluate(() => (window as any).__pg.getState().reviewId)).toBe("r2");
});

test("a review answered before its frames arrive still marks the alert frames, and a frame left out can be put back", async ({ page }) => {
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "review.get").length);
  const picture = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
  await dashboard(page, { engine: engine({ reviews: [review()] }), reviewId: "r1", snapshotCache: { a1: picture, s1: picture, s2: picture } });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  await expect(sheet.getByText("PrintGuard kept 3 frames from this print.")).toBeVisible();
  await expect.poll(asked).toBeGreaterThan(0);
  const onOpening = await asked();
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(asked).toBe(onOpening + 1);

  await sheet.getByRole("button", { name: "No, it failed" }).click();
  const frames = [
    { id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 },
    { id: "s1", ts: 120, score: 0.1, kind: "spaced", size: 1 },
    { id: "s2", ts: 180, score: 0.1, kind: "spaced", size: 1 },
  ];
  await emit(page, { event: "review", ...review(), frames });
  await expect(sheet.getByText("Real failure")).toBeVisible();
  await expect(sheet.getByText("Good")).toHaveCount(2);

  await sheet.getByRole("button", { name: /^Don't send/ }).nth(1).click();
  await expect(sheet.getByRole("button", { name: "Send 2 frames" })).toBeVisible();
  await sheet.getByRole("button", { name: /^Send the frame at/ }).click();
  await sheet.getByRole("button", { name: "Send 3 frames" }).click();
  expect(await sent(page, "review.send")).toMatchObject({ id: "r1", failures: ["a1"], removed: [] });

  await sheet.getByRole("button", { name: "Close print review" }).click();
  expect(await page.evaluate(() => (window as any).__pg.getState().snapshotCache)).toEqual({});
});

test("the history sheet says when it has not loaded, and breaks its line between prints", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const sheet = page.getByRole("dialog", { name: "Prusa · history" });
  await expect(sheet.getByText("loading history")).toHaveCount(2);
  await expect(sheet.getByText("No alerts have fired yet")).toBeHidden();

  const now = 1_700_000_040;
  const bucket = (t: number) => ({ t, min: 0.1, max: 0.3, sum: 0.4, n: 2, defects: 0 });
  const buckets = [now - 3000, now - 2940, now - 600, now - 540].map(bucket);
  await emit(page, { event: "history", monitor_id: "m1", now, buckets, snaps: [], alerts: [], stats: {} });
  await expect(sheet.getByText("No alerts have fired yet")).toBeVisible();
  await expect(sheet.getByRole("img", { name: "Risk over time" }).locator('path[fill="none"]')).toHaveCount(2);
});

test("the history sheet asks for the rollup once, then again only when an alert is kept", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "history.get").length);
  const sheet = page.getByRole("dialog", { name: "Prusa · history" });
  await expect(sheet).toBeVisible();
  const onOpening = await asked();
  expect(onOpening).toBeGreaterThan(0);
  for (const ts of [1, 2, 3]) await emit(page, { event: "result", monitor_id: "m1", ts, score: 0.42 });
  await expect(sheet.getByRole("img", { name: "risk 42%" })).toBeVisible();
  expect(await asked()).toBe(onOpening);

  const running = { id: "r1", monitor_id: "m1", status: "running", started: 1, ended: null, frames: 1, alerts: 1 };
  await emit(page, { event: "state", ...engine({ reviews: [running] }) });
  await expect.poll(asked).toBe(onOpening + 1);
});

test("a report whose send drops the socket fails with the dialog still usable", async ({ page }) => {
  await hub(page, (command, socket) => {
    if (command.cmd === "report.send") void socket.close();
  });
  await page.getByRole("button", { name: "Report a bug" }).click();
  await page.getByPlaceholder("What happened").fill("the feed froze");
  await page.getByRole("button", { name: "Send report" }).click();

  await expect(page.getByText("Sending failed")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send report" })).toBeEnabled();
});

test("only the tab that asked for the diagnostics downloads them", async ({ page }) => {
  await dashboard(page, { dialog: "report" });
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.getByRole("button", { name: "Download logs" }).click();
  const asked = await sent(page, "report.bundle");

  await emit(page, { event: "report_bundle", filename: "theirs.zip", zip: EMPTY_ZIP, req_id: "another-tab-1" });
  await page.waitForTimeout(300);
  expect(downloads).toBe(0);

  const download = page.waitForEvent("download");
  await emit(page, { event: "report_bundle", filename: "mine.zip", zip: EMPTY_ZIP, req_id: asked.req_id });
  expect((await download).suggestedFilename()).toBe("mine.zip");
});

test("a plugin sign-in opens its tab inside the click, sends it on when the hub answers and closes it on a refusal", async ({ page, context }) => {
  await context.route("https://accounts.example/**", (route) => route.fulfill({ contentType: "text/html", body: "<title>provider</title>" }));
  await dashboard(page);
  const signIn = async () => {
    const opened = context.waitForEvent("page");
    const asked = await page.evaluate(() => {
      (window as any).__pg.getState().signIn("demo");
      return (window as any).__sent.at(-1);
    });
    return { tab: await opened, asked };
  };

  const { tab, asked } = await signIn();
  expect(asked).toMatchObject({ cmd: "plugin.oauth", id: "demo", action: "start", origin: new URL(page.url()).origin });
  expect(tab.url()).toBe("about:blank");
  await emit(page, { event: "plugin_oauth", id: "demo", url: "https://accounts.example/authorize?state=theirs", req_id: "another-tab-1" });
  await page.waitForTimeout(300);
  expect(tab.url()).toBe("about:blank");

  await emit(page, { event: "plugin_oauth", id: "demo", url: "https://accounts.example/authorize?state=mine", req_id: asked.req_id });
  await expect(tab).toHaveURL("https://accounts.example/authorize?state=mine");
  expect(await tab.evaluate(() => window.opener)).toBeNull();

  const refused = await signIn();
  await emit(page, { event: "error", message: "demo needs a client id", req_id: refused.asked.req_id });
  await expect.poll(() => refused.tab.isClosed()).toBe(true);
});

test("two tabs never issue the same request id", async ({ page, context }) => {
  const other = await context.newPage();
  const ids = [];
  for (const tab of [page, other]) {
    await dashboard(tab);
    await tab.evaluate(() => (window as any).__pg.getState().send({ cmd: "discover" }));
    ids.push((await sent(tab, "discover")).req_id);
  }
  expect(ids[0]).not.toBe(ids[1]);
});

test("a camera that fails to register stops its publisher", async ({ page }) => {
  await dashboard(page);
  await page.evaluate(async () => {
    const win = window as any;
    const { published } = await import("/src/stream.ts" as string);
    published.set("dev-bench-1", () => (win.__stopped = true));
    win.__pg.getState().addPublishedCamera("Bench", "dev-bench-1");
  });
  const asked = await sent(page, "camera.add");
  await emit(page, { event: "error", message: "camera limit reached", req_id: asked.req_id });

  expect(await page.evaluate(() => (window as any).__stopped)).toBe(true);
});

test("a publisher stops when its camera is removed elsewhere or its registration is never sent", async ({ page }) => {
  await dashboard(page);
  const stopped = () => page.evaluate(() => (window as any).__stopped ?? []);
  await page.evaluate(async () => {
    const win = window as any;
    win.__stopped = [];
    const { published } = await import("/src/stream.ts" as string);
    for (const path of ["dev-bench-1", "dev-shelf-2", "dev-door-3"]) published.set(path, () => (published.delete(path), win.__stopped.push(path)));
  });
  await emit(page, { event: "state", ...engine() });
  expect(await stopped()).toEqual([]);

  await emit(page, { event: "state", ...engine({ cameras: [camera(), camera({ id: "c2", source: { kind: "path", path: "dev-bench-1" } })] }) });
  expect(await stopped()).toEqual([]);
  await emit(page, { event: "state", ...engine() });
  expect(await stopped()).toEqual(["dev-bench-1"]);

  await page.evaluate(() => {
    const store = (window as any).__pg;
    store.setState({ link: { send: () => false, close() {} } });
    store.getState().addPublishedCamera("Shelf", "dev-shelf-2");
  });
  expect(await stopped()).toEqual(["dev-bench-1", "dev-shelf-2"]);
});

test("a spinner outlasts another command's failure, and another tab's answers and failures stay in that tab", async ({ page }) => {
  await dashboard(page);
  const store = <T>(read: string) => page.evaluate((read) => (window as any).__pg.getState()[read], read) as Promise<T>;
  await page.evaluate(() => {
    const state = (window as any).__pg.getState();
    state.send({ cmd: "monitor.remove", id: "m1" });
    state.testPrinter("new", "octoprint", {});
    state.testNotifier("ntfy", {});
    state.discover();
  });
  await emit(page, { event: "error", message: "no monitor m1", req_id: (await sent(page, "monitor.remove")).req_id });
  expect(await store("testing")).toBe("new");
  expect(await store("testingNotifier")).toBe("ntfy");
  expect(await store("discovering")).toBe(true);
  expect(await store<unknown[]>("toasts")).toHaveLength(1);

  await emit(page, { event: "error", message: "another tab's mistake", req_id: "othertab-1" });
  await emit(page, { event: "notify_test", provider: "ntfy", ok: true, req_id: "othertab-2" });
  await emit(page, { event: "discovered", sources: [], req_id: "othertab-3" });
  expect(await store<unknown[]>("toasts")).toHaveLength(1);
  expect(await store("notifyTest")).toBeNull();
  expect(await store("discovering")).toBe(true);

  await emit(page, { event: "error", message: "unknown provider", req_id: (await sent(page, "printer.test")).req_id });
  expect(await store("testing")).toBeNull();
  expect(await store("testingNotifier")).toBe("ntfy");
  await emit(page, { event: "notify_test", provider: "ntfy", ok: true, req_id: (await sent(page, "notify.test")).req_id });
  expect(await store("testingNotifier")).toBeNull();
});

test("a monitor that is off or on standby shows no live figures and says which it is", async ({ page }) => {
  await dashboard(page, {
    engine: engine({ monitors: [monitor({ watching: false }), monitor({ id: "m2", name: "Voron", enabled: false, watching: false })] }),
    history: { m1: [{ ts: 1, score: 0.9 }], m2: [{ ts: 1, score: 0.9 }] },
  });
  const tiles = page.locator("article");
  await expect(tiles).toHaveCount(2);
  for (const tile of await tiles.all()) {
    await expect(tile).not.toContainText("5.0/5.0");
    await expect(tile.getByRole("img", { name: "risk unknown" })).toBeVisible();
  }
  await expect(tiles.nth(0).getByText("standby", { exact: true })).toBeVisible();
  await expect(tiles.nth(1).getByText("off", { exact: true })).toBeVisible();
});

test("two layout edits in a row both hold through a stale tick and go out as one save", async ({ page }) => {
  await dashboard(page);
  await page.evaluate(() => {
    const state = (window as any).__pg.getState();
    state.mutateLayout("monitors", (section: any) => ({ ...section, pinned: ["m1"] }));
    state.mutateLayout("monitors", (section: any) => ({ ...section, hidden: ["m9"] }));
  });
  await emit(page, { event: "state", ...engine() });
  const shown = () => page.evaluate(() => (window as any).__pg.getState().engine.settings.layout.monitors);
  expect(await shown()).toMatchObject({ pinned: ["m1"], hidden: ["m9"] });

  await expect.poll(() => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "settings.update"))).toHaveLength(1);
  expect((await sent(page, "settings.update")).patch.layout.monitors).toMatchObject({ pinned: ["m1"], hidden: ["m9"] });
});

test("an edit made just before the tab closes is sent as the page hides", async ({ page }) => {
  await dashboard(page);
  const saved = await page.evaluate(() => {
    (window as any).__pg.getState().updateMonitor("m1", { threshold: 0.4 });
    window.dispatchEvent(new Event("pagehide"));
    return (window as any).__sent.find((c: any) => c.cmd === "monitor.update");
  });

  expect(saved.patch).toEqual({ threshold: 0.4 });
});

test("the dashboard loads with site storage blocked", async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    }),
  );
  await page.routeWebSocket(/\/api\/ws$/, (socket) => socket.send(JSON.stringify({ event: "state", ...engine() })));
  await page.goto("/");

  await expect(page.getByText("Connecting to hub")).toBeHidden();
  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().phase)).toBe("ready");
  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  expect(await page.evaluate(() => (window as any).__pg.getState().dialog)).toBeNull();
});

test("a heater target the printer refuses goes back to what the printer has", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }), detailId: "m1" });
  const target = page.getByRole("spinbutton", { name: "nozzle target" });
  await target.fill("250");
  await target.blur();
  await expect(target).toBeDisabled();
  await expect(target).toHaveValue("250");

  await emit(page, { event: "error", message: "the printer refused 250", req_id: (await sent(page, "printer.heat")).req_id });
  await expect(target).toBeEnabled();
  await expect(target).toHaveValue("0");
});

test("the register form keeps what was typed when the printer is refused and clears once it is added", async ({ page }) => {
  await dashboard(page, { dialog: "printers" });
  const service = page.getByRole("combobox");
  await service.selectOption("octoprint");
  await page.getByPlaceholder(/^Name/).fill("Bench printer");
  const requests = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "printer.add"));

  await page.getByRole("button", { name: "Register printer" }).click();
  await emit(page, { event: "error", message: "no printer answered there", req_id: (await requests())[0].req_id });
  await expect(page.getByPlaceholder(/^Name/)).toHaveValue("Bench printer");

  await page.getByRole("button", { name: "Register printer" }).click();
  await expect.poll(async () => (await requests()).length).toBe(2);
  const added = { id: "p1", name: "Bench printer", provider: "octoprint", config: {}, online: true, device_state: null };
  await emit(page, { event: "state", ...engine({ printers: [added] }), req_id: (await requests())[1].req_id });
  await expect(page.getByPlaceholder(/^Name/)).toBeHidden();
  await expect(service.last()).toHaveValue("");
});

test("a plugin check that was never sent is asked again", async ({ page }) => {
  await dashboard(page);
  const asked = await page.evaluate(() => {
    const win = window as any;
    const link = win.__pg.getState().link;
    win.__pg.setState({ link: { send: () => false, close() {} } });
    win.__pg.getState().checkPlugin("pip");
    win.__pg.setState({ link });
    win.__pg.getState().checkPlugin("pip");
    return win.__sent.filter((c: any) => c.cmd === "plugin.code").length;
  });

  expect(asked).toBe(1);
});

test("a feed the browser cannot stream itself is asked for again after it fails", async ({ page }) => {
  let asked = 0;
  await page.addInitScript(() => {
    delete (window as any).MediaSource;
    delete (window as any).ManagedMediaSource;
    delete (window as any).WebKitMediaSource;
  });
  await page.route(/\/hls\/c1\//, (route) => (asked++, route.fulfill({ status: 404, body: "" })));
  await dashboard(page);

  await expect.poll(() => asked, { timeout: 10_000 }).toBeGreaterThan(1);
});

test("a feed the browser refuses to autoplay offers a tap to play", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    document.addEventListener("click", () => (win.__tapped = true), true);
    HTMLMediaElement.prototype.play = function () {
      if (!win.__tapped) return Promise.reject(new DOMException("autoplay is off", "NotAllowedError"));
      this.dispatchEvent(new Event("play"));
      return Promise.resolve();
    };
  });
  await page.route(/\/hls\/c1\//, (route) => route.abort());
  await dashboard(page);
  const tap = page.locator("article").getByRole("button", { name: "Tap to play" });
  await expect(tap).toBeVisible();

  await tap.click();
  await expect(tap).toBeHidden();
  expect(await page.evaluate(() => (window as any).__pg.getState().detailId)).toBeNull();
});

test("sounds held back by the autoplay policy are dropped, not played together later", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    win.__tones = 0;
    win.__waiting = [];
    win.AudioContext = class {
      currentTime = 0;
      destination = {};
      resume = () => new Promise<void>((allow) => win.__waiting.push(allow));
      createGain = () => ({ gain: { value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (next: unknown) => next });
      createOscillator = () => (win.__tones++, { frequency: { setValueAtTime() {} }, connect: (next: unknown) => next, start() {}, stop() {} });
    };
  });
  await dashboard(page);
  const chime = () =>
    page.evaluate(async () => {
      const { play } = await import("/src/sound.ts" as string);
      play([{ hz: 440, ms: 100 }]);
    });
  const allow = () => page.evaluate(() => (window as any).__waiting.splice(0).forEach((allowed: () => void) => allowed()));
  await chime();
  await chime();
  await page.waitForTimeout(1200);
  await allow();
  await chime();
  await allow();

  await expect.poll(() => page.evaluate(() => (window as any).__tones)).toBe(1);
});

test("a camera floating in picture in picture keeps playing behind a dialog and in a hidden tab", async ({ page }) => {
  let starts = 0;
  await page.route(/\/hls\/c1\//, () => void starts++);
  await dashboard(page);
  const attached = () => page.evaluate(() => document.querySelector("video")!.hasAttribute("src") || document.querySelector("video")!.childElementCount > 0);
  const float = (floating: boolean) =>
    page.evaluate((floating) => {
      const video = document.querySelector("video")!;
      Object.defineProperty(document, "pictureInPictureElement", { configurable: true, get: () => (floating ? video : null) });
      if (!floating) video.dispatchEvent(new Event("leavepictureinpicture"));
    }, floating);
  const hide = (hidden: boolean) =>
    page.evaluate((hidden) => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
      document.dispatchEvent(new Event("visibilitychange"));
    }, hidden);
  const cover = (dialog: string | null) => page.evaluate((dialog) => (window as any).__pg.setState({ dialog }), dialog);
  await expect.poll(attached).toBe(true);

  await float(true);
  await cover("report");
  await hide(true);
  await page.waitForTimeout(300);
  expect(await attached()).toBe(true);
  expect(starts).toBe(1);

  await float(false);
  await expect.poll(attached).toBe(false);
  await hide(false);
  await cover(null);
  await expect.poll(() => starts).toBe(2);
});

async function stagePrint(page: Page, megabytes = 0) {
  await page.addInitScript(() => {
    const win = window as any;
    const text = Blob.prototype.text;
    const send = XMLHttpRequest.prototype.send;
    win.__reads = 0;
    win.__uploads = [];
    Blob.prototype.text = function () {
      if (this instanceof File) win.__reads++;
      return text.call(this);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (body instanceof Blob) win.__uploads.push(body);
      send.call(this, body);
    };
  });
  await page.route(/\/api\/prints\/inspect/, (route) =>
    route.fulfill({ json: { meta: { slicer: "Cura", time_s: 5400, filament_g: 12, nozzle: 215, bed: 60 }, thumbnail: false } }),
  );
  await page.route(/\/api\/prints\?/, (route) => route.fulfill({ json: {} }));
  await dashboard(page);
  await page.evaluate((megabytes) => {
    const gcode = "G1 Z0.2\nG1 X10 Y10 E1\nG1 X20 Y10 E2\nG1 Z0.4\nG1 X20 Y20 E3\n";
    const file = new File([gcode, new Uint8Array(megabytes * 1024 * 1024).fill(10)], "cube.gcode");
    (window as any).__pg.getState().stagePrints([file]);
  }, megabytes);
}

const uploads = (page: Page) =>
  page.evaluate(() => Promise.all((window as any).__uploads.map(async (body: Blob) => ({ size: body.size, start: await body.slice(0, 64).text() }))));

test("a sliced file the browser cannot draw is uploaded as it is", async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return kind.includes("webgl") ? null : (getContext as any).call(this, kind, ...rest);
    } as typeof getContext;
  });
  await stagePrint(page);
  await expect(page.getByText("could not draw this file")).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect.poll(() => uploads(page)).toEqual([{ size: 58, start: "G1 Z0.2\nG1 X10 Y10 E1\nG1 X20 Y10 E2\nG1 Z0.4\nG1 X20 Y20 E3\n" }]);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("a preview that fails to draw on upload leaves nothing behind, and the file is read once", async ({ page }) => {
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
      return kind.includes("webgl") && this.style.position === "fixed" ? null : (getContext as any).call(this, kind, ...rest);
    } as typeof getContext;
  });
  await stagePrint(page);
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect.poll(() => uploads(page)).toEqual([{ size: 58, start: "G1 Z0.2\nG1 X10 Y10 E1\nG1 X20 Y10 E2\nG1 Z0.4\nG1 X20 Y20 E3\n" }]);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => document.querySelectorAll("body > canvas").length)).toBe(0);
  expect(await page.evaluate(() => (window as any).__reads)).toBe(1);
});

test("a file too large to draw says so, still shows what the hub read from it and uploads", async ({ page }) => {
  await stagePrint(page, 33);
  await expect(page.getByText("files over 32 MB are not drawn")).toBeVisible();
  await expect(page.getByText("1h 30m")).toBeVisible();
  await expect(page.getByText("12 g")).toBeVisible();
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect.poll(async () => (await uploads(page))[0]?.size).toBe(58 + 33 * 1024 * 1024);
  expect(await page.evaluate(() => (window as any).__reads)).toBe(0);
});

async function stageArchive(page: Page, files: Record<string, Uint8Array>) {
  const archive = Buffer.from(zipSync(files, { level: 1 })).toString("base64");
  await page.addInitScript(() => {
    const win = window as any;
    const fetch = win.fetch;
    win.fetch = async (url: string, init: RequestInit) => {
      if (url.includes("prints/inspect")) win.__sample = { size: (init.body as Blob).size, start: await (init.body as Blob).slice(0, 26).text() };
      return fetch(url, init);
    };
    win.__largestBlob = 0;
    win.Blob = new Proxy(Blob, {
      construct(target, parts, newTarget) {
        const blob = Reflect.construct(target, parts, newTarget);
        win.__largestBlob = Math.max(win.__largestBlob, blob.size);
        return blob;
      },
    });
  });
  await page.route(/\/api\/prints\/inspect/, (route) =>
    route.fulfill({ json: { meta: { slicer: "BambuStudio", time_s: 5400, filament_g: 12, nozzle: 220, bed: 55 }, thumbnail: true } }),
  );
  await dashboard(page);
  await page.evaluate(async (archive) => {
    const bytes = Uint8Array.from(atob(archive), (char) => char.charCodeAt(0));
    (window as any).__largestBlob = 0;
    (window as any).__pg.getState().stagePrints([new File([bytes], "plate.3mf")]);
  }, archive);
}

test("a sliced 3mf draws its lowest plate", async ({ page }) => {
  const plate = (number: number) => new TextEncoder().encode(`; plate ${number}\nG1 Z0.2\nG1 X10 Y10 E1\nG1 X20 Y10 E2\nG1 Z0.4\nG1 X20 Y20 E3\n`);
  await stageArchive(page, { "3D/3dmodel.model": new Uint8Array(8), "Metadata/plate_2.gcode": plate(2), "Metadata/plate_1.gcode": plate(1) });

  await expect(page.getByRole("slider", { name: "Layers shown" })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__sample)).toEqual({ size: 68, start: "; plate 1\nG1 Z0.2\nG1 X10 Y" });
});

test("a sliced 3mf's plate over the drawing limit is never unpacked whole", async ({ page }) => {
  const lines = ["; first line of the plate"];
  for (let size = 0, line = 0; size < 33 * 1024 * 1024; size += lines.at(-1)!.length + 1, line++) {
    lines.push(`G1 X${(line * 7919) % 25000} Y${(line * 104729) % 25000} E${line}`);
  }
  await stageArchive(page, { "3D/3dmodel.model": new Uint8Array(8), "Metadata/plate_1.gcode": new TextEncoder().encode(lines.join("\n")) });

  await expect(page.getByText("files over 32 MB are not drawn")).toBeVisible();
  await expect(page.getByText("1h 30m")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__sample)).toEqual({ size: 4 * 1024 * 1024 + 1 + 512 * 1024, start: "; first line of the plate\n" });
  expect(await page.evaluate(() => (window as any).__largestBlob)).toBeLessThan(8 * 1024 * 1024);
});

test("closing a drawn toolpath gives its WebGL context back", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    win.__contextsLost = 0;
    const getExtension = WebGL2RenderingContext.prototype.getExtension;
    WebGL2RenderingContext.prototype.getExtension = function (this: WebGL2RenderingContext, name: string) {
      const extension = (getExtension as any).call(this, name);
      if (name !== "WEBGL_lose_context" || !extension) return extension;
      return { loseContext: () => (win.__contextsLost++, extension.loseContext()) };
    } as typeof getExtension;
  });
  await stagePrint(page);
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Discard", exact: true }).click();

  await expect.poll(() => page.evaluate(() => (window as any).__contextsLost)).toBe(1);
});

const printFile = (over = {}) => ({
  id: "f1", name: "Benchy", filename: "benchy.gcode", ext: "gcode", size: 2048, printer_ids: [], uploaded: 1, thumbnail: null,
  meta: { slicer: null, time_s: null, filament_g: null, filament_mm: null, printer_model: null, nozzle: null, bed: null }, ...over,
});

const library = (prints: unknown[]) => {
  const printer = { provider: "octoprint", config: {}, online: true, device_state: { status: "idle" } };
  return {
    dialog: "prints",
    engine: engine({
      prints,
      printers: [{ id: "p1", name: "MK4", ...printer }, { id: "p2", name: "Mini", ...printer }],
      integrations: [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: ["gcode"], heater_control: true, schema: { properties: {} } }],
    }),
  };
};

test("two printers tagged in quick succession are both sent, without a printer that is gone", async ({ page }) => {
  await dashboard(page, library([printFile({ printer_ids: ["gone"] })]));
  await expect(page.getByText("none of its printers is registered")).toBeVisible();
  await page.getByRole("button", { name: "MK4", exact: true }).click();
  await page.getByRole("button", { name: "Mini", exact: true }).click();

  await expect(page.getByRole("button", { name: "✓ MK4" })).toHaveAttribute("aria-pressed", "true");
  const lastUpdate = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "print.update").at(-1)?.patch);
  await expect.poll(lastUpdate).toEqual({ printer_ids: ["p1", "p2"] });
});

test("removing or sending one file leaves the other rows' buttons alone", async ({ page }) => {
  await dashboard(page, library([printFile(), printFile({ id: "f2", name: "Vase", uploaded: 0, meta: { time_s: 7190 } })]));
  await expect(page.getByText("2h 0m")).toBeVisible();
  await page.getByRole("button", { name: "Print", exact: true }).first().click();
  await page.getByRole("button", { name: "Remove", exact: true }).first().click();

  await expect(page.getByRole("button", { name: "Sending…" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Removing…" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Print", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Remove", exact: true })).toBeEnabled();
});

test("a file dropped beside the drop zone is staged, and the page stays where it is", async ({ page }) => {
  await page.route(/\/api\/prints\/inspect/, (route) => route.fulfill({ json: { meta: {}, thumbnail: true } }));
  await dashboard(page, library([]));
  const dropped = (target: string, kind: "file" | "text") =>
    page.evaluate(
      ([target, kind]) => {
        const dataTransfer = new DataTransfer();
        if (kind === "file") dataTransfer.items.add(new File(["G1 X1\n"], "stray.gcode"));
        else dataTransfer.setData("text/plain", "words");
        const handled = (type: string) => !document.querySelector(target)!.dispatchEvent(new DragEvent(type, { dataTransfer, bubbles: true, cancelable: true }));
        return [handled("dragover"), handled("drop")];
      },
      [target, kind],
    );

  expect(await dropped("dialog h2", "text")).toEqual([false, false]);
  expect(await dropped("dialog h2", "file")).toEqual([true, true]);
  await expect(page.getByRole("heading", { name: "Upload stray.gcode" })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__pg.getState().staged.length)).toBe(1);
});

test("a printer test result shows only under the printer that was tested", async ({ page }) => {
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true, device_state: null };
  await dashboard(page, { engine: engine({ printers: [printer] }), dialog: "printers" });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("combobox").selectOption("octoprint");
  await page.getByRole("button", { name: "Test connection" }).first().click();
  const asked = await sent(page, "printer.test");
  await emit(page, { event: "printer_test", ok: true, status: "printing", req_id: asked.req_id });

  await expect(page.getByText("ok, printing")).toHaveCount(1);
  await expect(page.locator(".panel .panel").getByText("ok, printing")).toBeVisible();
});

test("selecting text out past the edge of a dialog leaves it open", async ({ page }) => {
  await dashboard(page, { dialog: "report" });
  const description = page.getByPlaceholder("What happened");
  await description.fill("the feed froze");
  const box = (await description.boundingBox())!;
  await page.mouse.move(box.x + 20, box.y + 15);
  await page.mouse.down();
  await page.mouse.move(5, 5, { steps: 5 });
  await page.mouse.up();
  await expect(description).toBeVisible();

  await page.mouse.click(5, 5);
  await expect(description).toBeHidden();
});

test("a page that fails to draw says so and offers a reload", async ({ page }) => {
  await dashboard(page);
  await page.evaluate(() => {
    const store = (window as any).__pg;
    const engine = store.getState().engine;
    store.setState({ engine: { ...engine, settings: { ...engine.settings, layout: { monitors: { order: 5 } } } } });
  });

  await expect(page.getByRole("alert").getByText("PrintGuard hit an error drawing this page.")).toBeVisible();
  await page.getByRole("button", { name: "Reload" }).click();
  await expect(page.getByRole("alert")).toBeHidden();
});

test("closing settings part way through a theme puts the saved theme back", async ({ page }) => {
  await dashboard(page, { dialog: "settings", settingsTab: "appearance" });
  await page.getByRole("button", { name: "+ New" }).click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Switch theme" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-glass", "");
});

test("a theme started from dark keeps dark text on its accent", async ({ page }) => {
  await dashboard(page);
  const themed = { ...engine().settings, theme: "mine", themes: [{ id: "mine", name: "Mine", base: "dark", colors: {} }] };
  await emit(page, { event: "state", ...engine({ settings: themed }) });

  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).toBe("#0b0c0a");
});

test("glass keeps status colours readable over a bright picture, blurs behind a sheet and forgets a picture that fails to load", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  await emit(page, { event: "state", ...engine({ settings: { ...engine().settings, theme: "glass" } }) });
  const lowestRatio = await page.evaluate(async () => {
    const loaded = performance.getEntriesByType("resource").find((entry) => entry.name.includes("/src/theme.ts"))!.name;
    const { measureCover } = await import(/* @vite-ignore */ loaded);
    const picture = document.createElement("canvas");
    picture.getContext("2d")!.fillStyle = "#ffffff";
    picture.getContext("2d")!.fillRect(0, 0, picture.width, picture.height);
    await measureCover(picture.toDataURL());

    const linear = (level: number) => (level <= 0.03928 ? level / 12.92 : ((level + 0.055) / 1.055) ** 2.4);
    const luminance = ([red, green, blue]: number[]) => 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
    const [tone, , , tint] = document.documentElement.style.getPropertyValue("--glass-surface").match(/[\d.]+/g)!.map(Number);
    const surface = linear(tint * (tone / 255) + (1 - tint));
    const probe = document.body.appendChild(document.createElement("span"));
    return Math.min(
      ...["accent", "ok", "warn", "bad"].map((token) => {
        probe.style.color = `var(--color-${token})`;
        const status = luminance(getComputedStyle(probe).color.match(/[\d.]+/g)!.slice(0, 3).map((channel) => Number(channel) / 255));
        return (Math.max(status, surface) + 0.05) / (Math.min(status, surface) + 0.05);
      }),
    );
  });
  expect(lowestRatio).toBeGreaterThanOrEqual(4.5);
  await expect(page.getByRole("dialog", { name: "Prusa" }).locator("aside")).not.toHaveCSS("backdrop-filter", "none");

  const tint = await page.evaluate(async () => {
    const loaded = performance.getEntriesByType("resource").find((entry) => entry.name.includes("/src/theme.ts"))!.name;
    const { measureCover } = await import(/* @vite-ignore */ loaded);
    await measureCover("data:image/png;base64,AAAA");
    return document.documentElement.style.getPropertyValue("--glass-surface");
  });
  expect(tint).toBe("rgb(0 0 0 / 0.000)");
});

test("copy works where the clipboard API is missing", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Navigator.prototype, "clipboard", { get: () => undefined });
    document.addEventListener("copy", () => ((window as any).__copied = (document.activeElement as HTMLTextAreaElement).value));
  });
  await dashboard(page, { dialog: "settings", settingsTab: "api", createdToken: { name: "ci", secret: "pg_once" } });
  await page.getByRole("button", { name: "Copy" }).click();

  await expect(page.getByRole("button", { name: "Copied" })).toBeFocused();
  expect(await page.evaluate(() => (window as any).__copied)).toBe("pg_once");
});

test("a toast raised over a dialog is part of it, so it is announced and can be reached", async ({ page }) => {
  await dashboard(page, { dialog: "report" });
  await page.evaluate(() => (window as any).__pg.getState().toast("alert", "Defect on Prusa"));
  const toast = page.getByRole("dialog").getByRole("alert");

  await expect(toast).toHaveText("Defect on Prusa");
  const box = (await toast.boundingBox())!;
  const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.textContent, [box.x + box.width / 2, box.y + box.height / 2]);
  expect(hit).toBe("Defect on Prusa");
});

test("the consecutive slider reaches the engine's limit, and the detection rate at its top lifts the cap", async ({ page }) => {
  await dashboard(page, { engine: engine({ monitors: [monitor({ consecutive: 20 })] }), detailId: "m1" });
  await expect(page.getByRole("slider", { name: "Consecutive detections to alert" })).toHaveValue("20");

  await page.evaluate(() => (window as any).__pg.setState({ detailId: null, dialog: "cameras" }));
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const rate = page.getByRole("slider", { name: "Detection rate" });
  await rate.fill("10");
  await rate.fill("30");
  const lastPatch = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "camera.update").at(-1)?.patch);
  await expect.poll(lastPatch).toEqual({ detect_fps: 60 });
});

test("a camera form empties once its camera is registered, and its fields are named", async ({ page }) => {
  await dashboard(page, { dialog: "cameras" });
  await page.getByRole("textbox", { name: "Name" }).fill("Garage");
  const address = page.getByRole("textbox", { name: "Stream URL" });
  await address.fill("rtsp://garage/stream");
  await page.getByRole("button", { name: "Register stream" }).click();
  const { req_id } = await sent(page, "camera.add");
  await emit(page, { event: "state", req_id, ...engine({ cameras: [camera(), camera({ id: "c2", name: "Garage" })] }) });
  await expect(address).toHaveValue("");

  await page.evaluate(() => (window as any).__pg.setState({ dialog: "monitor" }));
  await expect(page.getByRole("combobox", { name: "Camera" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Printer" })).toBeVisible();
});

test("a camera's address is shown without its password, and an idle one reads none", async ({ page }) => {
  const source = { kind: "url", url: "rtsp://admin:p@ss/w0rd@cam.local/stream?token=1" };
  await dashboard(page, { engine: engine({ cameras: [camera({ source, in_use: false })] }) });

  await expect(page.getByText("rtsp://cam.local/stream?token=1")).toBeVisible();
  await expect(page.getByText("none")).toHaveCount(2);
});

test("only an adjusted camera has its pixels read back each frame", async ({ page }) => {
  await page.goto("/");
  const reads = await page.evaluate(async () => {
    const path = "/src/image.ts";
    const { renderVideoFrame } = await import(/* @vite-ignore */ path);
    const video = Object.assign(document.createElement("canvas"), { videoWidth: 64, videoHeight: 48 });
    const canvas = document.body.appendChild(document.createElement("canvas"));
    const ctx = canvas.getContext("2d")!;
    const read = ctx.getImageData.bind(ctx);
    let count = 0;
    ctx.getImageData = (...area: Parameters<typeof read>) => {
      count += 1;
      return read(...area);
    };
    const framed = { brightness: 1, contrast: 1, sharpness: 0, crop: { x: 0, y: 0, w: 0.5, h: 0.5 }, rotation: 90 };
    renderVideoFrame(ctx, video, canvas, framed);
    const whenOnlyFramed = count;
    renderVideoFrame(ctx, video, canvas, { ...framed, brightness: 1.2 });
    return [whenOnlyFramed, count];
  });
  expect(reads).toEqual([0, 1]);
});

test("a guide action opens the settings tab it names, and no dash or arrow glyph is left in the copy", async ({ page }) => {
  for (const [action, tab] of [["Open settings", "Appearance"], ["Manage access", "API"], ["Browse plugins", "Plugins"]]) {
    await dashboard(page, { dialog: "guide" });
    expect(await page.getByRole("dialog").innerText()).not.toMatch(/[—→←↗]/);
    await expect(page.getByRole("link", { name: "Documentation opens in a new tab" })).toBeVisible();
    await page.getByRole("button", { name: action }).click();
    await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
  }
});

test("each getting started step has its own button name", async ({ page }) => {
  await dashboard(page, { engine: engine({ cameras: [], monitors: [] }) });
  for (const step of ["Register a camera", "Frame the print", "Connect a printer", "Set up alerts", "Add a monitor"]) {
    await expect(page.getByRole("button", { name: `Open ${step}`, exact: true })).toBeVisible();
  }
});

test("a report attachment is picked from a button, and the picker is left empty so the same file can be added again", async ({ page }) => {
  await dashboard(page, { dialog: "report" });
  const screenshot = { name: "shot.png", mimeType: "image/png", buffer: Buffer.from("png") };
  const attach = page.getByRole("button", { name: "Attach screenshots" });
  await attach.focus();
  await expect(attach).toBeFocused();
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (await chooser).setFiles(screenshot);
  await expect(page.getByText("shot.png")).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveJSProperty("value", "");
});

test("a slider is named by its label and reads its formatted value", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  const threshold = page.getByRole("slider", { name: "Alert threshold", exact: true });

  await expect(threshold).toHaveAttribute("aria-valuetext", "0.60");
  await expect(page.getByRole("switch", { name: "Watch this monitor", exact: true })).toBeVisible();
});

test("an alerting tile opens from its banner, and an offline camera shows no inference figures", async ({ page }) => {
  await dashboard(page, {
    engine: engine({ cameras: [camera({ online: false })], monitors: [monitor({ alert: { score: 0.9, action: "pause", ts: 1 } })] }),
    history: { m1: [{ ts: 1, score: 0.9 }] },
  });
  const tile = page.locator("article");
  await expect(tile).not.toContainText("5.0/5.0");
  await expect(tile.getByRole("img", { name: "risk unknown" })).toBeVisible();

  const banner = (await page.getByText("DEFECT DETECTED").boundingBox())!;
  await page.mouse.click(banner.x + banner.width / 2, banner.y + banner.height / 2);
  await expect(page.getByRole("dialog", { name: "Prusa" })).toBeVisible();
});
