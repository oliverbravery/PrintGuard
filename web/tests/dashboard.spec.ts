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
    store.send({ cmd: "printer.remove", id: "p1" });
  });
  await expect.poll(() => updates().length).toBe(1);

  await sockets[0].close();
  await expect(page.getByRole("status").getByText("reconnecting")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__pg.getState().isPending("printer.remove"))).toBe(false);
  await page.evaluate(() => (window as any).__pg.getState().send({ cmd: "printer.remove", id: "p1" }));
  expect(await page.evaluate(() => (window as any).__pg.getState().isPending("printer.remove"))).toBe(false);

  await expect.poll(() => updates().length, { timeout: 8000 }).toBe(2);
  await expect(page.getByText("reconnecting")).toBeHidden();
  expect(updates()[1].patch).toEqual({ threshold: 0.4 });
  sockets[1].send(JSON.stringify({ event: "state", ...engine({ monitors: [monitor({ threshold: 0.4 })] }), req_id: updates()[1].req_id }));
  await expect.poll(() => page.evaluate(() => Object.keys((window as any).__pg.getState().optimistic).length)).toBe(0);
});

test("a warning raised while the hub started is toasted once per page load, not on every state or reconnect", async ({ page }) => {
  const warnings = ["The GPU cannot run the model, using the CPU", "Dropped a camera the hub no longer accepts"];
  const state = engine({ startup_warnings: warnings });
  const { sockets } = await hub(page, undefined, state);
  for (const warning of warnings) await expect(page.getByText(warning)).toHaveCount(1);

  sockets[0].send(JSON.stringify({ event: "state", ...state }));
  await sockets[0].close();
  await expect.poll(() => sockets.length, { timeout: 8000 }).toBe(2);
  sockets[1].send(JSON.stringify({ event: "state", ...state }));
  await expect(page.getByText("reconnecting")).toBeHidden();
  for (const warning of warnings) await expect(page.getByText(warning)).toHaveCount(1);
});

test("the update dialog opened while the hub is away asks for the releases once it is back", async ({ page }) => {
  await dashboard(page, { dialog: "update", reconnecting: true });
  await expect(page.getByRole("dialog", { name: "Updates" })).toBeVisible();
  expect(await sent(page, "update.releases")).toBeUndefined();

  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(() => sent(page, "update.releases")).toBeDefined();
});

test("a dashboard left open through an update reloads onto the new version", async ({ page }) => {
  const { sockets } = await hub(page);
  sockets[0].send(JSON.stringify({ event: "state", ...engine({ version: "next" }) }));
  await expect.poll(() => sockets.length).toBe(2);
});

test("a setting changed while another is still saving is sent on its own", async ({ page }) => {
  const { commands } = await hub(page);
  const updates = () => commands.filter((c) => c.cmd === "settings.update").map((c) => c.patch);
  await page.evaluate(() => (window as any).__pg.getState().updateSettings({ update_check: false }));
  await expect.poll(updates).toEqual([{ update_check: false }]);
  await page.evaluate(() => (window as any).__pg.getState().updateSettings({ theme: "light" }));
  await expect.poll(updates).toEqual([{ update_check: false }, { theme: "light" }]);
});

test("a setting still saving holds its value when a later setting is acknowledged first", async ({ page }) => {
  const { sockets, commands } = await hub(page);
  const updates = () => commands.filter((c) => c.cmd === "settings.update");
  const pendingFields = () => page.evaluate(() => Object.keys((window as any).__pg.getState().optimistic.settings?.patch ?? {}));
  await page.evaluate(() => {
    const state = (window as any).__pg.getState();
    state.updateSettings({ inference_runtime: "onnx" });
    state.flushUpdates();
    state.updateSettings({ update_check: false });
    state.flushUpdates();
  });
  await expect.poll(() => updates().length).toBe(2);

  sockets[0].send(JSON.stringify({ event: "state", ...engine(), req_id: updates()[1].req_id }));
  await expect.poll(pendingFields).toEqual(["inference_runtime"]);
  expect(await page.evaluate(() => (window as any).__pg.getState().engine.settings.inference_runtime)).toBe("onnx");

  sockets[0].send(JSON.stringify({ event: "state", ...engine(), req_id: updates()[0].req_id }));
  await expect.poll(pendingFields).toEqual([]);
});

test("a rename still waiting to send is dropped when its monitor or camera is deleted", async ({ page }) => {
  const { commands } = await hub(page);
  await page.evaluate(() => {
    const store = (window as any).__pg.getState();
    store.updateMonitor("m1", { name: "Renamed" });
    store.send({ cmd: "monitor.remove", id: "m1" });
    store.updateCamera("c1", { name: "Renamed" });
    store.send({ cmd: "camera.remove", id: "c1" });
  });
  await expect.poll(() => commands.filter((c) => c.cmd.endsWith(".remove")).length).toBe(2);
  await page.waitForTimeout(500);
  expect(commands.filter((c) => c.cmd.endsWith(".update"))).toEqual([]);
  expect(await page.evaluate(() => Object.keys((window as any).__pg.getState().optimistic))).toEqual([]);
});

test("a setting the hub refuses goes back on screen before the next state", async ({ page }) => {
  const { commands, sockets } = await hub(page);
  await page.evaluate(() => (window as any).__pg.getState().updateMonitor("m1", { threshold: 0.2 }));
  await expect.poll(() => commands.filter((c) => c.cmd === "monitor.update").length).toBe(1);
  expect(await page.evaluate(() => (window as any).__pg.getState().engine.monitors[0].threshold)).toBe(0.2);

  sockets[0].send(JSON.stringify({ event: "error", message: "threshold refused", req_id: commands.at(-1).req_id }));
  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().engine.monitors[0].threshold)).toBe(0.6);
});

test("a boot screen that cannot reach the hub says what to check", async ({ page }) => {
  await page.routeWebSocket(/\/api\/ws$/, (socket) => void socket.close());
  await page.goto("/");
  await expect(page.getByText("Connecting to hub")).toBeVisible();
  await expect(page.getByText(/The hub is not answering.*WebSockets.*Origin/)).toBeVisible({ timeout: 10_000 });
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
  const { sockets } = await hub(page);
  await page.evaluate(() => (window as any).__pg.getState().openDetail("m1"));
  await page.routeWebSocket(/\/api\/ws$/, (socket) => void socket.close());
  await sockets[0].close();
  await expect(page.getByRole("status").getByText("reconnecting")).toBeVisible();
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

test("one kept frame is not called frames on the tile or in the review sheet", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 1 })] }), reviewId: "r1" });
  await expect(page.getByRole("button", { name: "Review 1 frame from the last print" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Prusa · review" }).getByText("PrintGuard kept 1 frame from this print.")).toBeVisible();
});

test("the review's answer buttons sit in a group named by their question and the printer model has a name", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review()] }), reviewId: "r1" });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  const question = sheet.getByRole("group", { name: "Did this print finish fine?" });
  await expect(question.getByRole("button")).toHaveText(["Yes", "No, it failed"]);

  await question.getByRole("button", { name: "Yes" }).click();
  await expect(sheet.getByRole("textbox", { name: "Printer model" })).toBeVisible();
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
  await sheet.getByRole("button", { name: /^Send frame \d of \d at/ }).click();
  await sheet.getByRole("button", { name: "Send 3 frames" }).click();
  expect(await sent(page, "review.send")).toMatchObject({ id: "r1", failures: ["a1"], removed: [] });

  await sheet.getByRole("button", { name: "Close print review" }).click();
  expect(await page.evaluate(() => (window as any).__pg.getState().snapshotCache)).toEqual({});
});

test("a review frame shows whole whatever its shape and any frame opens full size", async ({ page }) => {
  const square = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>')}`;
  const frames = [
    { id: "s1", ts: 60, score: 0.1, kind: "spaced", size: 1 },
    { id: "a1", ts: 120, score: 0.9, kind: "alert", action: "pause", size: 1 },
  ];
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 2 })] }), reviewId: "r1", snapshotCache: { s1: square, a1: square } });
  await emit(page, { event: "review", ...review({ frames: 2 }), frames });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  await sheet.getByRole("button", { name: "Yes" }).click();
  await expect(sheet.locator("img")).toHaveCount(2);
  expect(await sheet.locator("img").first().evaluate((img) => getComputedStyle(img).objectFit)).toBe("contain");

  await sheet.getByRole("button", { name: /^Enlarge frame 1 of 2 at/ }).click();
  const enlarged = page.getByRole("dialog", { name: /10%/ });
  await expect(enlarged.locator("img")).toHaveAttribute("src", square);
  await page.keyboard.press("Escape");
  await expect(enlarged).toBeHidden();
  await expect(sheet).toBeVisible();
});

test("opening the history asks only for the snapshots near the screen", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const sheet = page.getByRole("dialog", { name: "Prusa · history" });
  const snaps = Array.from({ length: 90 }, (_, index) => ({ id: `s${index}`, ts: 1_700_000_000 - index, score: 0.9, action: "failed" }));
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_100, buckets: [], snaps, alerts: [], stats: {} });
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "snapshot.get").map((c: any) => c.id));
  await expect.poll(async () => (await asked()).length).toBeGreaterThan(0);
  expect((await asked()).length).toBeLessThan(30);

  await sheet.getByRole("button", { name: /Snapshot at 90% risk/ }).last().scrollIntoViewIfNeeded();
  await expect.poll(asked).toContain("s89");
});

test("a minute of history on its own is drawn across its width, not as a dot", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const chart = page.getByRole("dialog", { name: "Prusa · history" }).getByRole("img", { name: "Risk over time" });
  const bucket = (t: number) => ({ t, n: 10, sum: 4.5, min: 0.4, max: 0.5, defects: 10, watched: 60 });
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_200, buckets: [bucket(1_699_999_980), bucket(1_700_000_100)], snaps: [], alerts: [], stats: {} });

  await expect(chart.locator("path")).toHaveCount(4);
  const widths = await chart.locator("path").evaluateAll((paths) => paths.map((path) => path.getBoundingClientRect().width));
  for (const width of widths) expect(width).toBeGreaterThan(100);
});

test("a history chart spanning more than a day dates the ends of its axis", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const sheet = page.getByRole("dialog", { name: "Prusa · history" });
  const bucket = (t: number) => ({ t, n: 10, sum: 4.5, min: 0.4, max: 0.5, defects: 0, watched: 60 });
  const twoDays = 2 * 86_400;
  const ends = sheet.getByRole("img", { name: "Defect frames per period" }).locator("xpath=following-sibling::div[1]/span");
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_000 + twoDays, buckets: [bucket(1_700_000_000), bucket(1_700_000_000 + twoDays)], snaps: [], alerts: [], stats: {} });
  await sheet.getByRole("button", { name: "all", exact: true }).click();

  const [first, last] = await ends.allTextContents();
  expect(first).not.toBe(last);
});

test("after a hub restart the alerts tile still counts the snapshots that were kept", async ({ page }) => {
  await dashboard(page, { statsMonitorId: "m1" });
  const snaps = [1, 2, 3].map((index) => ({ id: `s${index}`, ts: 1_700_000_000 - index, score: 0.9, action: "failed" }));
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_100, buckets: [], snaps, alerts: [], stats: { alerts: 0, snaps: 3 } });
  await expect(page.getByText("alerts", { exact: true }).locator("xpath=preceding-sibling::div")).toHaveText("3");
});

test("a failure card at the narrowest phone keeps its time and score inside the card", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 1 })] }), reviewId: "r1" });
  await emit(page, { event: "review", ...review({ frames: 1 }), frames: [{ id: "a1", ts: 120, score: 0.9, kind: "alert", action: "pause", size: 1 }] });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  await sheet.getByRole("button", { name: "No, it failed" }).click();

  const card = (await sheet.locator(".panel").filter({ hasText: "Real failure" }).boundingBox())!;
  const score = (await sheet.locator(".label", { hasText: "90%" }).boundingBox())!;
  expect(score.x).toBeGreaterThanOrEqual(card.x);
  expect(score.x + score.width).toBeLessThanOrEqual(card.x + card.width);
});

test("sheets and the page keep clear of the right safe area", async ({ page }) => {
  await dashboard(page);
  const insets = await page.evaluate(() =>
    [".app", ".sheet"].map((selector) =>
      [...document.styleSheets].flatMap((sheet) => [...sheet.cssRules]).some((rule) => rule instanceof CSSStyleRule && rule.selectorText === selector && rule.cssText.includes("safe-area-inset-right")),
    ),
  );
  expect(insets).toEqual([true, true]);
});

test("review frames whose pictures were lost to a reconnect are asked for again", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review()] }), reviewId: "r1" });
  await emit(page, { event: "review", ...review(), frames: [{ id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 }] });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  await sheet.getByRole("button", { name: "Yes" }).click();
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "snapshot.get").length);
  await expect.poll(asked).toBeGreaterThan(0);
  const before = await asked();

  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(asked).toBeGreaterThan(before);
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

test("a camera that cannot open says why in the camera rail", async ({ page }) => {
  const reason = "no decoder for this stream";
  await dashboard(page, { engine: engine({ cameras: [camera({ online: false, in_use: false, reason })] }) });
  await expect(page.getByText(reason)).toBeVisible();
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

test("the bed target can be typed while the nozzle target just set is still on its way to the printer", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const device = { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater };
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true, device_state: device };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }), detailId: "m1" });
  const nozzle = page.getByRole("spinbutton", { name: "nozzle target" });
  const bed = page.getByRole("spinbutton", { name: "bed target" });
  await nozzle.fill("215");
  await bed.click();
  await expect(nozzle).toBeDisabled();
  await expect(bed).toBeFocused();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("60");

  const answered = { ...device, nozzle: { actual: 21, target: 215 } };
  await emit(page, { event: "device", printer_id: "p1", req_id: (await sent(page, "printer.heat")).req_id, ...answered });
  await expect(nozzle).toBeEnabled();
  await expect(bed).toHaveValue("60");
});

test("a monitor name or heater target typed and left with Escape is still saved", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }), detailId: "m1" });
  const panel = page.getByRole("dialog", { name: "Prusa" });
  await panel.getByRole("textbox", { name: "Name" }).fill("Bench");
  await panel.getByRole("spinbutton", { name: "nozzle target" }).fill("215");
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();

  const commands = () => page.evaluate(() => (window as any).__sent.map((c: any) => [c.cmd, c.patch ?? c.nozzle]));
  expect(await commands()).toEqual(expect.arrayContaining([["monitor.update", { name: "Bench" }], ["printer.heat", 215]]));
  expect(await commands()).toHaveLength(2);
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

const CATALOGUED_SIGN_IN = {
  id: "player", name: "Player", version: "1.0.0", author: "someone", description: "Shows what is playing.", icon: "icon.png", media: [],
  repo: "someone/player", path: "", ref: "a".repeat(40), permissions: ["net", "oauth"], platforms: [], surfaces: ["panel"], digests: {},
};

const withCatalogue = async (page: Page) => {
  await page.route("https://raw.githubusercontent.com/**", (route) => route.fulfill({ status: 404, body: "" }));
  await dashboard(page, {
    engine: engine({
      plugin_permissions: [
        { id: "net", label: "Reach the internet", description: "", urls: true },
        { id: "oauth", label: "Sign in", description: "" },
      ],
    }),
  });
  await page.evaluate(() => (window as any).__pg.getState().openSettings("plugins"));
  await emit(page, { event: "catalogue", plugins: [CATALOGUED_SIGN_IN] });
};

test("the store page of a plugin that signs in draws before its manifest has arrived", async ({ page }) => {
  await withCatalogue(page);
  await page.getByRole("button", { name: "Player", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Player" })).toBeVisible();
  await expect(page.getByText("Sign in at")).toBeHidden();
  await expect(page.getByText("hit an error")).toBeHidden();
});

for (const [shape, manifest] of [
  ["null lists", { permissions: null, urls: null, consumes: null, reasons: null, provides: null, oauth: null }],
  ["numbers", { permissions: 5, urls: 7, consumes: 1, reasons: 2, provides: 3, oauth: 4 }],
  ["a sign-in with no address", { permissions: ["net", "oauth"], reasons: { net: "a", oauth: "b" }, oauth: { authorize_url: "nonsense", token_url: "x", label: "Player" } }],
] as const) {
  test(`a store page whose plugin.json holds ${shape} still draws`, async ({ page }) => {
    await withCatalogue(page);
    await page.route("https://raw.githubusercontent.com/**/plugin.json", (route) => route.fulfill({ json: manifest }));
    await page.getByRole("button", { name: "Player", exact: true }).click();

    await expect(page.getByRole("heading", { name: "Player" })).toBeVisible();
    await expect(page.getByText("Reach the internet")).toBeVisible();
    await expect(page.getByText("hit an error")).toBeHidden();
  });
}

test("an error that answers a command never reaches a plugin", async ({ page }) => {
  await page.goto("/");
  const seen = await page.evaluate(async () => {
    const path = "/src/plugins.ts";
    const { projectEvent } = await import(/* @vite-ignore */ path);
    const hooked = { error: ["message"] };
    const needs = { error: "state:read" };
    return [
      projectEvent({ event: "error", message: "no monitor [redacted]", req_id: "r1" }, hooked, ["state:read"], [], needs),
      projectEvent({ event: "error", message: "ntfy failed" }, hooked, ["state:read"], [], needs),
    ];
  });

  expect(seen).toEqual([null, { event: "error", message: "ntfy failed" }]);
});

test("a plugin in the store is opened by its name and installed by its own button", async ({ page }) => {
  await withCatalogue(page);
  const card = page.locator("div", { has: page.getByRole("button", { name: "Install" }) }).filter({ hasText: "Shows what is playing." }).last();

  expect(await card.getAttribute("role")).toBeNull();
  expect(await card.locator("[role=button] button, button button").count()).toBe(0);
  await card.getByRole("button", { name: "Install" }).click();
  expect((await sent(page, "plugin.install")).source.repo).toBe("someone/player");
  await expect(page.getByRole("heading", { name: "Player" })).toBeHidden();

  await page.getByRole("button", { name: "Player", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Player" })).toBeVisible();
});

const demoPlugin = (over = {}) => ({
  id: "demo",
  manifest: {
    id: "demo", name: "Demo", version: "1.0.0", description: "", author: "", homepage: "", permissions: ["state:read", "printer:control"], reasons: {},
    surfaces: ["panel"], platforms: [], assets: [], urls: [], secrets: {}, provides: {}, consumes: [], oauth: {}, events: [], tick_s: 0,
  },
  files: ["plugin.js"], digests: { "plugin.js": "aaa" }, source: { kind: "github", repo: "o/r", ref: "c0ffee1" },
  granted: ["state:read", "printer:control"], config: {}, secrets_set: [], verified: false, enabled: true, installed: 1, failure: null, ...over,
});

const withPlugins = (plugins: unknown[]) =>
  engine({
    plugins,
    plugin_permissions: [
      { id: "state:read", label: "Read", description: "", fields: {} },
      { id: "printer:control", label: "Control", description: "", commands: ["printer.action"] },
    ],
    plugin_assets: { png: "image/png" },
  });

const showing = (value: string) => `plugin.action((name, arg, ctx) => { ctx.store.picked = [arg]; });
plugin.render((ctx) => ({ type: "text", value: "${value}" + JSON.stringify(ctx.store) }));`;

const askedForCode = async (page: Page) => {
  await expect.poll(() => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "plugin.code").length)).toBeGreaterThan(0);
  return page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "plugin.code").at(-1).req_id);
};

const drawn = (page: Page) => page.evaluate(() => (window as any).__pg.getState().pluginTrees.demo?.value);

async function runningDemo(page: Page) {
  await dashboard(page);
  await emit(page, { event: "state", ...withPlugins([demoPlugin()]) });
  await emit(page, { event: "plugin_code", id: "demo", sources: { "plugin.js": showing("v1") }, assets: {}, req_id: await askedForCode(page) });
  await expect.poll(() => drawn(page)).toBe("v1{}");
}

test("an updated plugin restarts on its new code and is read again for the consent dialog", async ({ page }) => {
  await runningDemo(page);
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "plugin.code").length);
  const before = await asked();
  await page.evaluate(() => (window as any).__pg.getState().checkPlugin("demo"));
  await expect.poll(() => page.evaluate(() => Object.keys((window as any).__pg.getState().pluginFindings))).toEqual(["demo"]);

  await emit(page, { event: "state", ...withPlugins([demoPlugin({ digests: { "plugin.js": "bbb" } })]) });
  await expect.poll(asked).toBe(before + 1);
  expect(await page.evaluate(() => Object.keys((window as any).__pg.getState().pluginFindings))).toEqual([]);

  await emit(page, { event: "plugin_code", id: "demo", sources: { "plugin.js": showing("v2") }, assets: {}, req_id: await askedForCode(page) });
  await expect.poll(() => drawn(page)).toBe("v2{}");
});

test("a plugin's secret field is never filled by a password manager", async ({ page }) => {
  await dashboard(page, { engine: withPlugins([demoPlugin({ manifest: { ...demoPlugin().manifest, secrets: { api_key: "Your key" } } })]) });
  await page.evaluate(() => (window as any).__pg.getState().openSettings("plugins"));
  await emit(page, { event: "catalogue", plugins: [] });
  await page.getByRole("button", { name: "Demo", exact: true }).click();

  await expect(page.getByPlaceholder("Not set")).toHaveAttribute("autocomplete", "new-password");
});

test("a plugin panel is drawn on a hub with no monitors yet, beneath the way to add one", async ({ page }) => {
  await dashboard(page);
  await emit(page, { event: "state", ...withPlugins([demoPlugin()]), monitors: [], cameras: [] });
  await emit(page, { event: "plugin_code", id: "demo", sources: { "plugin.js": showing("v1") }, assets: {}, req_id: await askedForCode(page) });

  await expect(page.getByRole("heading", { name: "Demo" })).toBeVisible();
  await expect(page.getByText("Register a camera", { exact: true }).first()).toBeVisible();
});

test("a removed plugin leaves nothing of its own behind and frees its files", async ({ page }) => {
  await dashboard(page);
  await page.evaluate(() => {
    const revoked: string[] = [];
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.revokeObjectURL = (url) => (revoked.push(url), revoke(url));
    (window as any).__revoked = revoked;
  });
  await emit(page, { event: "state", ...withPlugins([demoPlugin()]) });
  await emit(page, { event: "plugin_page", id: "demo", page: { "README.md": "" } });
  await emit(page, {
    event: "plugin_code", id: "demo", sources: { "plugin.js": showing("v1") }, assets: { "a.png": "iVBORw0KGgo=" }, req_id: await askedForCode(page),
  });
  await expect.poll(() => drawn(page)).toBe("v1{}");

  await emit(page, { event: "state", ...withPlugins([]) });
  const held = await page.evaluate(() => {
    const state = (window as any).__pg.getState();
    return ["pluginTrees", "pluginViews", "pluginAssets", "pluginPages", "pluginFindings", "pluginPanels"].flatMap((key) => Object.keys(state[key]));
  });
  expect(held).toEqual([]);
  expect(await page.evaluate(() => (window as any).__revoked.length)).toBe(1);
});

test("a plugin's stored data written while the hub is away is sent when it is back", async ({ page }) => {
  const { sockets, commands } = await hub(page, undefined, withPlugins([demoPlugin()]));
  const code = commands.find((c) => c.cmd === "plugin.code");
  sockets[0].send(JSON.stringify({ event: "plugin_code", id: "demo", sources: { "plugin.js": showing("v1") }, assets: {}, req_id: code.req_id }));
  await expect.poll(() => drawn(page)).toBe("v1{}");

  await sockets[0].close();
  await expect(page.getByRole("status").getByText("reconnecting")).toBeVisible();
  await page.evaluate(() => (window as any).__pg.getState().pluginAct("demo", "pick", "bench"));
  await expect.poll(() => drawn(page)).toBe('v1{"picked":["bench"]}');
  await expect.poll(() => commands.filter((c) => c.cmd === "plugin.update").length, { timeout: 8000 }).toBe(1);
  expect(commands.find((c) => c.cmd === "plugin.update").patch).toEqual({ config: { picked: ["bench"] } });
});

test("a refused write of a plugin's stored data lets the sandbox take what the hub holds", async ({ page }) => {
  await runningDemo(page);
  await page.evaluate(() => (window as any).__pg.getState().pluginAct("demo", "pick", "bench"));
  await expect.poll(() => drawn(page)).toBe('v1{"picked":["bench"]}');
  const written = await page.evaluate(() => (window as any).__sent.find((c: any) => c.cmd === "plugin.update"));

  await emit(page, { event: "error", message: "refused", req_id: written.req_id });
  await emit(page, { event: "state", ...withPlugins([demoPlugin({ config: { picked: ["shelf"] } })]) });
  await expect.poll(() => drawn(page)).toBe('v1{"picked":["shelf"]}');
});

test("a plugin sign-in tab that the hub never answered is closed when the connection drops", async ({ page, context }) => {
  const { sockets } = await hub(page);
  const opened = context.waitForEvent("page");
  await page.evaluate(() => (window as any).__pg.getState().signIn("demo"));
  const tab = await opened;

  await sockets[0].close();
  await expect.poll(() => tab.isClosed()).toBe(true);
});

test("a button a plugin draws says so when its command could not be sent", async ({ page }) => {
  await runningDemo(page);
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await emit(page, { event: "plugin_effect", id: "demo", effect: { kind: "command", cmd: { cmd: "printer.action", id: "p1", action: "pause" } } });

  await expect(page.getByText("The hub is reconnecting, so that wasn't sent")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "printer.action").length)).toBe(0);
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

test("a sound file asked for by a plugin that is only a worker is fetched and played", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    win.__played = [];
    win.Audio = class {
      constructor(public src: string) {}
      play() {
        win.__played.push(this.src);
        return Promise.resolve();
      }
    };
  });
  const plugin = {
    id: "chimes",
    manifest: {
      id: "chimes", name: "Chimes", version: "1.0.0", description: "", author: "", homepage: "", permissions: ["sound"],
      reasons: {}, surfaces: [], platforms: [], urls: [], secrets: {}, provides: {}, consumes: [], oauth: {}, events: [], tick_s: 0,
    },
    files: ["worker.js", "ding.mp3"], digests: {}, source: { kind: "zip" }, granted: ["sound"], config: {}, secrets_set: [],
    verified: false, enabled: true, installed: 0, failure: null,
  };
  const state = engine({ plugins: [plugin], plugin_assets: { mp3: "audio/mpeg" }, plugin_event_permissions: {} });
  await dashboard(page, { engine: state });
  await emit(page, { event: "state", ...state });
  const asked = await sent(page, "plugin.code");
  expect(asked.id).toBe("chimes");

  await emit(page, { event: "plugin_code", id: "chimes", sources: { "worker.js": "" }, assets: { "ding.mp3": "AAAA" }, req_id: asked.req_id });
  await emit(page, { event: "plugin_effect", id: "chimes", effect: { kind: "sound", asset: "ding.mp3" } });
  expect(await page.evaluate(() => (window as any).__played)).toEqual([expect.stringMatching(/^blob:/)]);
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

test("an upload the hub refuses stays in the sheet with what was typed, and closes it once accepted", async ({ page }) => {
  await stagePrint(page);
  const route = /\/api\/prints\?/;
  await page.route(route, (request) => request.fulfill({ status: 413, json: { detail: "the library is full" } }));
  const name = page.getByRole("textbox", { name: "Name" });
  await name.fill("Calibration cube");
  await page.getByRole("button", { name: "Upload", exact: true }).click();

  await expect(page.getByRole("alert")).toHaveText("the library is full");
  await expect(name).toHaveValue("Calibration cube");
  await expect(page.getByRole("button", { name: "Upload", exact: true })).toBeEnabled();

  await page.unroute(route);
  await page.route(route, (request) => request.fulfill({ json: {} }));
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(name).toBeHidden();
});

test("discarding or closing the sheet while a file uploads cancels the request", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    const abort = XMLHttpRequest.prototype.abort;
    win.__aborts = 0;
    XMLHttpRequest.prototype.abort = function () {
      win.__aborts++;
      abort.call(this);
    };
  });
  await stagePrint(page);
  await page.route(/\/api\/prints\?/, () => {});
  const upload = page.getByRole("button", { name: "Upload", exact: true });
  const aborts = () => page.evaluate(() => (window as any).__aborts);
  const stage = () => page.evaluate(() => (window as any).__pg.getState().stagePrints([new File(["G1 Z0.2\n"], "cube.gcode")]));

  const sentCount = () => page.evaluate(() => (window as any).__uploads.length);
  await upload.click();
  await expect.poll(sentCount).toBe(1);
  await page.getByRole("button", { name: "Discard" }).click();
  await expect.poll(aborts).toBe(1);
  expect(await page.evaluate(() => (window as any).__pg.getState().uploads)).toEqual([]);

  await stage();
  await upload.click();
  await expect.poll(sentCount).toBe(2);
  await page.getByRole("button", { name: "Cancel uploads" }).click();
  await expect.poll(aborts).toBe(2);
  expect(await page.evaluate(() => (window as any).__pg.getState().uploads)).toEqual([]);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("a sliced temperature cleared in the upload sheet says why Upload is off", async ({ page }) => {
  await stagePrint(page);
  const upload = page.getByRole("button", { name: "Upload", exact: true });
  const nozzle = page.getByRole("spinbutton", { name: "nozzle" });
  await expect(upload).toBeEnabled();
  await nozzle.fill("");
  await expect(page.getByText("Upload needs nozzle between 1 and 350 °C")).toBeVisible();
  await expect(upload).toBeDisabled();
  await expect(nozzle).not.toHaveAttribute("placeholder", "none");

  await nozzle.fill("215");
  await expect(page.getByText("Upload needs")).toBeHidden();
  await expect(upload).toBeEnabled();
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

test("the print library does not squeeze its list into a strip on a phone held sideways", async ({ page }) => {
  await page.setViewportSize({ width: 667, height: 375 });
  await dashboard(page, library([printFile({ id: "a", name: "First" }), printFile({ id: "b", name: "Second" }), printFile({ id: "c", name: "Third" })]));
  const scrollers = await page.evaluate(() =>
    [...document.querySelectorAll("dialog *")]
      .filter((el) => getComputedStyle(el).overflowY === "auto" && el.scrollHeight > el.clientHeight + 1)
      .map((el) => el.clientHeight),
  );
  expect(scrollers.length).toBeGreaterThan(0);
  expect(Math.min(...scrollers)).toBeGreaterThan(200);
});

test("two printers tagged in quick succession are both sent, without a printer that is gone", async ({ page }) => {
  await dashboard(page, library([printFile({ printer_ids: ["gone"] })]));
  await expect(page.getByText("none of its printers is registered")).toBeVisible();
  await page.getByRole("button", { name: "MK4", exact: true }).click();
  await page.getByRole("button", { name: "Mini", exact: true }).click();

  await expect(page.getByRole("button", { name: "✓ MK4" })).toHaveAttribute("aria-pressed", "true");
  const lastUpdate = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "print.update").at(-1)?.patch);
  await expect.poll(lastUpdate).toEqual({ printer_ids: ["p1", "p2"] });
});

test("a printer that cannot print a file is named in the text, not only a hover title", async ({ page }) => {
  await dashboard(page, library([printFile({ id: "f3", name: "Plate", filename: "plate.3mf", ext: "3mf" })]));

  await expect(page.getByText("MK4, Mini can't print .3mf files.")).toBeVisible();
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

test("a file uploaded seconds ago reads just now and an older one counts minutes", async ({ page }) => {
  const secondsAgo = (seconds: number) => Date.now() / 1000 - seconds;
  await dashboard(page, library([printFile({ uploaded: secondsAgo(5) }), printFile({ id: "f2", name: "Vase", uploaded: secondsAgo(150) })]));
  await expect(page.getByText("just now")).toHaveCount(1);
  await expect(page.getByText("2m ago")).toHaveCount(1);
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

test("a theme saved while the hub is away is sent once it is back", async ({ page }) => {
  const { sockets, commands } = await hub(page);
  await page.evaluate(() => (window as any).__pg.getState().openSettings("appearance"));
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("textbox", { name: "Theme name" }).fill("Workshop");
  await sockets[0].close();
  await expect(page.getByText("reconnecting")).toBeVisible();
  await page.getByRole("button", { name: "Save theme" }).click();

  await expect(page.getByRole("textbox", { name: "Theme name" })).toBeHidden();
  await expect.poll(() => commands.filter((c) => c.cmd === "settings.update").at(-1)?.patch.themes?.[0].name, { timeout: 8000 }).toBe("Workshop");
});

test("a saved theme stays on screen through a state sent before the hub has answered it", async ({ page }) => {
  await dashboard(page, { dialog: "settings", settingsTab: "appearance" });
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("textbox", { name: "Theme name" }).fill("Workshop");
  await page.getByRole("button", { name: "Save theme" }).click();
  await emit(page, { event: "state", ...engine() });
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).not.toBe("");

  const saved = await page.evaluate(() => (window as any).__pg.getState().engine.settings);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await emit(page, { event: "state", ...engine({ settings: saved }) });
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).toBe("");
});

test("a theme started from dark keeps dark text on its accent", async ({ page }) => {
  await dashboard(page);
  const themed = { ...engine().settings, theme: "mine", themes: [{ id: "mine", name: "Mine", base: "dark", colors: {} }] };
  await emit(page, { event: "state", ...engine({ settings: themed }) });

  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).toBe("#0b0c0a");
});

test("glass keeps status colours readable and distinct over a bright picture, blurs behind a sheet and forgets a picture that fails to load", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  await emit(page, { event: "state", ...engine({ settings: { ...engine().settings, theme: "glass" } }) });
  const { lowestRatio, colours } = await page.evaluate(async () => {
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
    const colours = ["accent", "ok", "warn", "bad"].map((token) => {
      probe.style.color = `var(--color-${token})`;
      return getComputedStyle(probe).color;
    });
    const lowestRatio = Math.min(
      ...colours.map((colour) => {
        const status = luminance(colour.match(/[\d.]+/g)!.slice(0, 3).map((channel) => Number(channel) / 255));
        return (Math.max(status, surface) + 0.05) / (Math.min(status, surface) + 0.05);
      }),
    );
    return { lowestRatio, colours };
  });
  expect(lowestRatio).toBeGreaterThanOrEqual(4.5);
  expect(new Set(colours).size).toBe(4);
  expect(colours).not.toContain("rgb(255, 255, 255)");
  await expect(page.getByRole("dialog", { name: "Prusa" }).locator("aside")).not.toHaveCSS("backdrop-filter", "none");

  const tint = await page.evaluate(async () => {
    const loaded = performance.getEntriesByType("resource").find((entry) => entry.name.includes("/src/theme.ts"))!.name;
    const { measureCover } = await import(/* @vite-ignore */ loaded);
    await measureCover("data:image/png;base64,AAAA");
    return document.documentElement.style.getPropertyValue("--glass-surface");
  });
  expect(tint).toBe("rgb(0 0 0 / 0.000)");
});

test("glass is tinted for the picture on show, not one taken down while it was still being measured", async ({ page }) => {
  await dashboard(page);
  await emit(page, { event: "state", ...engine({ settings: { ...engine().settings, theme: "glass" } }) });
  const tint = await page.evaluate(async () => {
    const loaded = performance.getEntriesByType("resource").find((entry) => entry.name.includes("/src/theme.ts"))!.name;
    const { measureCover } = await import(/* @vite-ignore */ loaded);
    const picture = document.createElement("canvas");
    picture.getContext("2d")!.fillStyle = "#ffffff";
    picture.getContext("2d")!.fillRect(0, 0, picture.width, picture.height);
    const takenDown = measureCover(picture.toDataURL());
    await measureCover(null);
    await takenDown;
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

test("Enter in a camera's name or address registers it", async ({ page }) => {
  await dashboard(page, { dialog: "cameras" });
  await page.getByRole("textbox", { name: "Stream URL" }).fill("rtsp://garage/stream");
  await page.getByRole("textbox", { name: "Name" }).press("Enter");
  expect(await sent(page, "camera.add")).toMatchObject({ name: "Stream", source: { kind: "url", url: "rtsp://garage/stream" } });
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

test("the guide holds the space for a picture before it has loaded, so nothing moves under a press", async ({ page }) => {
  await page.route("**/guide/*.jpg", () => {});
  await dashboard(page, { dialog: "guide" });
  const heights = await page.getByRole("dialog").locator("figure").evaluateAll((figures) => figures.map((figure) => figure.clientHeight));
  expect(Math.min(...heights)).toBeGreaterThan(40);
  await page.unrouteAll({ behavior: "ignoreErrors" });
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
  const chooser = page.waitForEvent("filechooser");
  await attach.press("Enter");
  await (await chooser).setFiles(screenshot);
  await expect(page.getByText("shot.png")).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveJSProperty("value", "");
});

test("the setup and introduction progress bars are named, and the file picker is not an unnamed tab stop", async ({ page }) => {
  await dashboard(page, { engine: engine({ cameras: [], monitors: [] }) });
  await expect(page.getByRole("progressbar", { name: "Setup progress" })).toBeVisible();

  await page.evaluate(() => (window as any).__pg.setState({ dialog: "intro" }));
  await expect(page.getByRole("progressbar", { name: "Introduction progress" })).toBeVisible();

  await page.evaluate(() => (window as any).__pg.setState({ dialog: "prints" }));
  await expect(page.getByRole("button", { name: "browse" })).toBeVisible();
  await expect(page.locator("input[type=file]")).toBeHidden();
});

test("the glass sliders read out percentages, and two review frames from one minute are told apart", async ({ page }) => {
  const settings = { ...engine().settings, glass: { opacity: 0.5, tone: 0.25 } };
  await dashboard(page, { engine: engine({ settings, reviews: [review({ frames: 2 })] }), reviewId: "r1" });
  await expect(page.getByRole("slider", { name: "Opacity", includeHidden: true }).first()).toHaveAttribute("aria-valuetext", "50%");
  await expect(page.getByRole("slider", { name: "Tone", includeHidden: true }).first()).toHaveAttribute("aria-valuetext", "25%");

  await emit(page, {
    event: "review", ...review({ frames: 2 }),
    frames: [{ id: "s1", ts: 60, score: 0.1, kind: "spaced", size: 1 }, { id: "s2", ts: 70, score: 0.1, kind: "spaced", size: 1 }],
  });
  const sheet = page.getByRole("dialog", { name: "Prusa · review" });
  await sheet.getByRole("button", { name: "Yes" }).click();
  await expect(sheet.getByRole("button", { name: /^Frame 1 of 2 at .*, marked Good/ })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^Frame 2 of 2 at .*, marked Good/ })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^Don't send frame 2 of 2 at / })).toBeVisible();
});

test("a slider is named by its label and reads its formatted value", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  const threshold = page.getByRole("slider", { name: "Alert threshold", exact: true });

  await expect(threshold).toHaveAttribute("aria-valuetext", "0.60");
  await expect(page.getByRole("switch", { name: "Watch this monitor", exact: true })).toBeVisible();
});

test("an alerting tile opens from its banner, and an offline camera shows no signal below it and no inference figures", async ({ page }) => {
  await dashboard(page, {
    engine: engine({ cameras: [camera({ online: false })], monitors: [monitor({ alert: { score: 0.9, action: "pause", ts: 1 } })] }),
    history: { m1: [{ ts: 1, score: 0.9 }] },
  });
  const tile = page.locator("article");
  await expect(tile).not.toContainText("5.0/5.0");
  await expect(tile.getByRole("img", { name: "risk unknown" })).toBeVisible();

  const banner = (await page.getByText("DEFECT DETECTED").boundingBox())!;
  const signal = (await tile.getByText("no signal").boundingBox())!;
  expect(signal.y).toBeGreaterThanOrEqual(banner.y + banner.height);
  await page.mouse.click(banner.x + banner.width / 2, banner.y + banner.height / 2);
  await expect(page.getByRole("dialog", { name: "Prusa" })).toBeVisible();
});

test("an offline camera shows no frame rate in the camera list and no risk in the history sheet", async ({ page }) => {
  const offline = engine({ cameras: [camera({ online: false })] });
  await dashboard(page, { engine: offline, history: { m1: [{ ts: 1, score: 0.9 }] } });
  const card = page.getByRole("button", { name: /Edit camera Workshop/ });
  await expect(card).not.toContainText("5.0");
  await expect(card.getByText("none")).toHaveCount(2);

  await page.evaluate(() => (window as any).__pg.getState().openStats("m1"));
  await expect(page.getByRole("dialog", { name: "Prusa · history" }).getByRole("img", { name: "risk unknown" })).toBeVisible();
});

test("the saved chip shows only on the form that saved", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  const panel = page.getByRole("dialog", { name: "Prusa" });
  const acknowledge = async (cmd: string) => {
    await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
    const { req_id } = await page.evaluate((cmd) => (window as any).__sent.findLast((c: any) => c.cmd === cmd), cmd);
    await emit(page, { event: "state", ...engine(), req_id });
  };

  await page.evaluate(() => (window as any).__pg.getState().updateSettings({ update_check: false }));
  await acknowledge("settings.update");
  expect(await page.evaluate(() => Object.keys((window as any).__pg.getState().savedAt))).toEqual(["settings"]);
  await expect(panel.getByText(/saved/)).toBeHidden();

  await page.evaluate(() => (window as any).__pg.getState().updateMonitor("m1", { threshold: 0.4 }));
  await acknowledge("monitor.update");
  await expect(panel.getByText(/saved/)).toBeVisible();
});

test("a settings tab shows saved only for what it saved itself", async ({ page }) => {
  await dashboard(page, { dialog: "settings", settingsTab: "updates" });
  const acknowledge = async () => {
    await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
    await emit(page, { event: "state", ...engine(), req_id: (await lastSent(page, "settings.update")).req_id });
  };
  await page.evaluate(() => (window as any).__pg.getState().updateSettings({ theme: "light" }));
  await acknowledge();
  await page.getByRole("tab", { name: "Updates" }).click();
  await expect(page.getByText(/saved ✓/)).toBeHidden();
  await page.getByRole("tab", { name: "Advanced" }).click();
  await expect(page.getByText(/saved ✓/)).toBeHidden();

  await page.getByRole("switch", { name: "Ask me to review frames after a print" }).click();
  await acknowledge();
  await expect(page.getByText(/saved ✓/)).toBeVisible();
  await page.getByRole("tab", { name: "Updates" }).click();
  await expect(page.getByText(/saved ✓/)).toBeHidden();
});

test("the updates tab opens the release notes whether or not an update is waiting", async ({ page }) => {
  await dashboard(page, { dialog: "settings", settingsTab: "updates" });
  await page.getByRole("tab", { name: "Updates" }).click();
  await page.getByRole("button", { name: "Release notes" }).click();
  expect(await page.evaluate(() => (window as any).__pg.getState().dialog)).toBe("update");
});

test("a token revoke greys out only its own button, and a token name stays until the hub accepts it", async ({ page }) => {
  const tokens = [
    { id: "t1", name: "ci", scope: "read", hint: "pg_aaaa" },
    { id: "t2", name: "ha", scope: "control", hint: "pg_bbbb" },
  ];
  await dashboard(page, { engine: engine({ tokens }), dialog: "settings", settingsTab: "api" });
  await page.getByRole("tab", { name: "API" }).click();
  await page.getByRole("button", { name: "Revoke" }).first().click();
  await expect(page.getByRole("button", { name: "Revoke" }).first()).toBeDisabled();
  await expect(page.getByRole("button", { name: "Revoke" }).last()).toBeEnabled();

  const name = page.getByRole("textbox", { name: "Token name" });
  await name.fill("backup");
  await page.getByRole("button", { name: "Generate" }).click();
  const created = await lastSent(page, "token.create");
  await emit(page, { event: "error", message: "no", req_id: created.req_id });
  await expect(name).toHaveValue("backup");
  await expect(page.getByRole("alert").filter({ hasText: "no" })).toBeVisible();

  await page.getByRole("button", { name: "Generate" }).click();
  await emit(page, { event: "state", ...engine({ tokens }), req_id: (await lastSent(page, "token.create")).req_id });
  await expect(name).toHaveValue("");
});

test("an alert says what happened to the print, and nothing for alert only", async ({ page }) => {
  await dashboard(page, { engine: engine({ monitors: [monitor({ alert: { score: 0.9, action: "none", ts: 1 } })] }), detailId: "m1" });
  await emit(page, { event: "alert", monitor_id: "m1", score: 0.9, action: "none", ts: 1 });
  await emit(page, { event: "alert", monitor_id: "m1", score: 0.9, action: "pause", ts: 2 });
  const panel = page.getByRole("dialog", { name: "Prusa" });

  await expect(panel.getByRole("alert").first()).toHaveText("Defect on Prusa, 90%");
  await expect(panel.getByRole("alert").last()).toHaveText("Defect on Prusa, 90%, print paused");
  await expect(panel.getByText("defect at 90%", { exact: true })).toBeVisible();
});

test("the add monitor dialog stays open with what was typed when the add fails, and drops a camera removed elsewhere", async ({ page }) => {
  await dashboard(page, { dialog: "monitor" });
  const dialog = page.getByRole("dialog", { name: "Add monitor" });
  await dialog.getByRole("textbox", { name: "Monitor name" }).fill("Voron");
  await dialog.getByRole("combobox", { name: "Camera" }).selectOption("c1");
  await dialog.getByRole("button", { name: "Add monitor" }).click();
  await emit(page, { event: "error", message: "the state could not be saved", req_id: (await sent(page, "monitor.add")).req_id });

  await expect(dialog.getByRole("textbox", { name: "Monitor name" })).toHaveValue("Voron");
  await emit(page, { event: "state", ...engine({ cameras: [] }) });
  await expect(dialog.getByRole("button", { name: "Add monitor" })).toBeDisabled();
});

test("a printer test result goes when the form it tested is edited, and a trailing space is not an unsaved name", async ({ page }) => {
  const schema = { properties: { url: { title: "Address" } } };
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: { url: "http://mk4" }, online: true, device_state: null };
  const integrations = [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema }];
  await dashboard(page, { engine: engine({ printers: [printer], integrations }), dialog: "printers" });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Test connection" }).click();
  await emit(page, { event: "printer_test", ok: true, status: "idle", req_id: (await sent(page, "printer.test")).req_id });
  await expect(page.getByText("ok, idle")).toBeVisible();

  await page.getByRole("textbox", { name: "Name" }).fill("MK4 ");
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await expect(page.getByText("ok, idle")).toBeVisible();
  await page.getByRole("textbox", { name: "Address" }).fill("http://mk3");
  await expect(page.getByText("ok, idle")).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Address" })).toHaveAttribute("autocapitalize", "none");
});

test("a connection or alert test that was never sent leaves its button free", async ({ page }) => {
  const schema = { properties: { url: { title: "Address" } } };
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: { url: "http://mk4" }, online: true, device_state: null };
  const integrations = [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema }];
  await dashboard(page, { engine: engine({ printers: [printer], integrations }), dialog: "printers" });
  await page.evaluate(() => (window as any).__pg.setState({ link: { send: () => false, close() {} } }));
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Test connection" }).click();

  await expect(page.getByRole("status").filter({ hasText: "wasn't sent" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Test connection" })).toBeEnabled();
  expect(await page.evaluate(() => (window as any).__pg.getState().testing)).toBeNull();
  expect(
    await page.evaluate(() => {
      const store = (window as any).__pg.getState();
      store.testNotifier("ntfy", "ntfy", {});
      return (window as any).__pg.getState().testingNotifier;
    }),
  ).toBeNull();
});

test("a device scan that was never sent does not read as scanning, or as finished", async ({ page }) => {
  await dashboard(page, { dialog: "cameras" });
  await page.evaluate(() => (window as any).__pg.setState({ link: { send: () => false, close() {} } }));
  await page.getByRole("button", { name: "This machine" }).click();

  await expect(page.getByRole("button", { name: "This machine" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("scanning devices")).toBeHidden();
  await expect(page.getByText("no unregistered cameras found")).toBeHidden();
});

test("removing a camera the hub never hears about leaves it publishing and remembered for the next load", async ({ page }) => {
  const publishing = camera({ id: "c2", name: "Bench", source: { kind: "path", path: "dev-bench-1" } });
  await dashboard(page, { engine: engine({ cameras: [publishing] }), dialog: "cameras" });
  await page.evaluate(async () => {
    const win = window as any;
    const stream = await import("/src/stream.ts" as string);
    stream.published.set("dev-bench-1", () => (win.__stopped = true));
    localStorage.setItem("pg-publishers", JSON.stringify({ "dev-bench-1": "usb" }));
    win.__pg.setState({ link: { send: () => false, close() {} } });
  });
  await page.getByRole("button", { name: "Remove" }).click();

  expect(await page.evaluate(() => (window as any).__stopped)).toBeUndefined();
  expect(await page.evaluate(() => localStorage.getItem("pg-publishers"))).toContain("dev-bench-1");
});

test("a hub that never answers the connection is tried again", async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(() => {
    const win = window as any;
    win.__dialled = 0;
    win.WebSocket = class {
      static OPEN = 1;
      readyState = 0;
      constructor(url: string) {
        if (url.endsWith("/api/ws")) win.__dialled++;
      }
      close() {}
      send() {}
    };
  });
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => (window as any).__dialled)).toBe(1);
  await page.clock.runFor(12_000);
  await expect.poll(() => page.evaluate(() => (window as any).__dialled)).toBe(2);
});

test("a preset temperature can be cleared and retyped, and pause is off for a paused print", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "paused", progress: 40, job: "benchy", remaining_s: 60, nozzle: heater, bed: heater },
  };
  const settings = { ...engine().settings, preheat: [{ name: "PLA", nozzle: 200, bed: 60 }] };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })], settings }), detailId: "m1" });
  const panel = page.getByRole("dialog", { name: "Prusa" });
  await expect(panel.getByRole("button", { name: "pause" })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "resume" })).toBeEnabled();

  await panel.getByRole("button", { name: "Edit" }).click();
  const nozzle = panel.getByRole("spinbutton", { name: "PLA nozzle target" });
  await nozzle.fill("");
  await expect(nozzle).toHaveValue("");
  await nozzle.pressSequentially("210");
  await expect(nozzle).toHaveValue("210");
  await nozzle.blur();
  await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
  expect((await sent(page, "settings.update")).patch.preheat).toEqual([{ name: "PLA", nozzle: 210, bed: 60 }]);
});

test("a page that was frozen for longer than the silence limit does not drop a hub that kept talking", async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(() => {
    const win = window as any;
    win.__dialled = 0;
    win.WebSocket = class {
      static OPEN = 1;
      readyState = 1;
      onopen: (() => void) | null = null;
      constructor(url: string) {
        if (!url.endsWith("/api/ws")) return;
        win.__dialled++;
        setTimeout(() => this.onopen?.(), 0);
      }
      close() {}
      send() {}
    };
  });
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => (window as any).__dialled)).toBe(1);
  await page.clock.fastForward(12_000);
  await page.clock.runFor(2_000);
  expect(await page.evaluate(() => (window as any).__dialled)).toBe(1);

  await page.clock.runFor(11_000);
  await page.clock.runFor(2_000);
  expect(await page.evaluate(() => (window as any).__dialled)).toBe(2);
});

test("pause, resume and cancel are each enabled only when the printer's state allows them", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = (status: string) => ({
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status, progress: 40, job: "benchy", remaining_s: 60, nozzle: heater, bed: heater },
  });
  const expected: Record<string, boolean[]> = { idle: [true, false, false], printing: [true, false, true], paused: [false, true, true] };
  for (const [status, [pause, resume, cancel]] of Object.entries(expected)) {
    await dashboard(page, { engine: engine({ printers: [printer(status)], monitors: [monitor({ printer_id: "p1" })] }), detailId: "m1" });
    const panel = page.getByRole("dialog", { name: "Prusa" });
    await expect(panel.getByRole("button", { name: "pause" })).toBeEnabled({ enabled: pause });
    await expect(panel.getByRole("button", { name: "resume" })).toBeEnabled({ enabled: resume });
    await expect(panel.getByRole("button", { name: "cancel" })).toBeEnabled({ enabled: cancel });
  }
});

test("a heater target typed or stored above the limit is never sent as it is", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  const settings = { ...engine().settings, preheat: [{ name: "PLA", nozzle: 400, bed: 200 }] };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })], settings }), detailId: "m1" });
  const panel = page.getByRole("dialog", { name: "Prusa" });
  await panel.getByRole("button", { name: /^PLA/ }).click();
  expect(await sent(page, "printer.heat")).toMatchObject({ nozzle: 350, bed: 150 });

  await panel.getByRole("button", { name: "Edit" }).click();
  const nozzle = panel.getByRole("spinbutton", { name: "PLA nozzle target" });
  await nozzle.fill("999");
  await nozzle.blur();
  await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
  expect((await sent(page, "settings.update")).patch.preheat).toEqual([{ name: "PLA", nozzle: 350, bed: 150 }]);
});

test("the header wraps instead of scrolling the page when a chip is added at its tightest widths", async ({ page }) => {
  const state = { reconnecting: true, engine: engine({ update: { available: true, latest: "9.9.9" } }) };
  for (const width of [640, 1024]) {
    await page.setViewportSize({ width, height: 800 });
    await dashboard(page, state);
    await expect(page.getByText("reconnecting")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
});

test("a long toast stays inside a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 852 });
  await dashboard(page);
  await page.evaluate(() => (window as any).__pg.getState().toast("error", "The hub is reconnecting, so that wasn't sent. Try again in a moment."));
  const box = (await page.getByRole("status").filter({ hasText: "reconnecting, so" }).boundingBox())!;

  expect(box.x).toBeGreaterThanOrEqual(16);
  expect(box.x + box.width).toBeLessThanOrEqual(393 - 16);
});

test("a print that kept no frames is not offered for review, and a snapshot is opened and closed on its own", async ({ page }) => {
  const reviews = [review({ status: "dismissed", frames: 0 }), review({ id: "r2", frames: 4 })];
  await dashboard(page, { engine: engine({ reviews }), statsMonitorId: "m1" });
  const sheet = page.getByRole("dialog", { name: "Prusa · history" });
  const snap = { id: "s1", ts: 1_700_000_000, score: 0.9, action: "failed" };
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_040, buckets: [], snaps: [snap], alerts: [], stats: {} });
  await expect(sheet.getByRole("listitem")).toHaveCount(1);
  await expect(sheet.getByRole("listitem")).toContainText("4 frames");

  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "snapshot.get").length);
  const onOpening = await asked();
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(asked).toBeGreaterThan(onOpening);

  await sheet.getByRole("button", { name: /Snapshot at 90% risk/ }).click();
  const enlarged = page.getByRole("dialog", { name: /90% · 40s ago · the printer did not take the command/ });
  await expect(enlarged.getByRole("button", { name: "Close snapshot" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(enlarged).toBeHidden();
  await expect(sheet).toBeVisible();
});

test("a tile behind a panel says its feed is paused", async ({ page }) => {
  await dashboard(page, { detailId: "m1" });
  await expect(page.locator("article").getByText("feed paused")).toBeAttached();
});

test("a camera with no Remove says why in the text", async ({ page }) => {
  const owned = camera({ id: "c2", name: "Printer cam", printer_id: "p1" });
  const declared = camera({ id: "c3", name: "Passed in", declared: true });
  const printers = [{ id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true, device_state: null }];
  await dashboard(page, { dialog: "cameras", engine: engine({ cameras: [owned, declared], printers }) });

  await expect(page.getByText("Passed in by the deployment, remove its devices entry to remove this camera.")).toBeVisible();
  await page.getByRole("tab", { name: "Printer cameras" }).click();
  await expect(page.getByText("Managed by its printer integration, remove the printer to remove this camera.")).toBeVisible();
});

test("camera and settings controls are named, and toggle buttons say which is selected", async ({ page }) => {
  await dashboard(page, { dialog: "cameras", focusCameraId: "c1" });
  await expect(page.getByRole("img", { name: "online" })).toBeVisible();
  await expect(page.getByRole("button", { name: "0°", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "90°" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("textbox", { name: "Stream URL" })).toHaveAttribute("autocapitalize", "none");

  await page.evaluate(() => (window as any).__pg.getState().openSettings("api"));
  await expect(page.getByRole("combobox", { name: "Token scope" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Token name" })).toBeVisible();
  await page.getByRole("tab", { name: "Alerts" }).click();
  await expect(page.getByText("for monitors with push notifications on")).toBeVisible();
});

test("a dialog opened with the pointer shows no focus ring until the keyboard is used", async ({ page }) => {
  await dashboard(page);
  await page.getByRole("button", { name: "+ Camera" }).click();
  const close = page.getByRole("button", { name: "Close dialog" });
  await expect(close).toBeFocused();
  await expect(close).toHaveCSS("outline-style", "none");

  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveCSS("outline-style", "solid");
});

test.describe("on a touch screen", () => {
  test.use({ hasTouch: true, viewport: { width: 393, height: 852 } });

  test("the header's more button takes a tap 44 pixels across", async ({ page }) => {
    await dashboard(page);
    const box = (await page.getByRole("button", { name: "More" }).boundingBox())!;
    const centre = [box.x + box.width / 2, box.y + box.height / 2];
    const hits = await page.evaluate(
      (points) => points.map(([x, y]) => document.elementFromPoint(x, y)?.closest("button")?.getAttribute("aria-label")),
      [[centre[0] - 21, centre[1]], [centre[0], centre[1] - 21], [centre[0], centre[1] + 21]],
    );
    expect(hits).toEqual(["More", "More", "More"]);
  });
});

test("a stored file is drawn from what arrives, and one over the limit is cut off without a length to go by", async ({ page }) => {
  await page.addInitScript(() => {
    const win = window as any;
    const fetch = win.fetch;
    win.fetch = async (url: string, init: RequestInit) => {
      if (!String(url).endsWith("/gcode")) return fetch(url, init);
      const megabyte = new Uint8Array(1024 * 1024).fill(10);
      let sent = 0;
      const body = new ReadableStream({
        pull: (controller) => (sent++ < win.__megabytes ? controller.enqueue(megabyte) : controller.close()),
        cancel: () => void (win.__cancelledAt = sent),
      });
      return new Response(win.__megabytes ? body : "G1 Z0.2\nG1 X10 Y10 E1\nG1 Z0.4\nG1 X20 Y20 E2\n");
    };
  });
  await dashboard(page, { engine: engine({ prints: [printFile()] }), printId: "f1" });
  await expect(page.getByRole("slider", { name: "Layers shown" })).toBeVisible();

  await page.evaluate(() => {
    (window as any).__megabytes = 40;
    (window as any).__pg.setState({ printId: null });
  });
  await page.evaluate(() => (window as any).__pg.setState({ printId: "f1" }));
  await expect(page.getByText("files over 32 MB are not drawn")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__cancelledAt)).toBeLessThan(36);
});

const KEPT_HINT = "Saved. Leave blank to keep it";
const keyedSchema = {
  properties: { url: { title: "Address" }, api_key: { title: "API key", secret: true } },
  required: ["url", "api_key"],
};
const keyedPrinter = (over = {}) => ({
  id: "p1", name: "MK4", provider: "octoprint", config: { url: "http://mk4" }, secrets_set: ["api_key"], online: true, device_state: null, ...over,
});
const keyedIntegrations = [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema: keyedSchema }];
const lastSent = (page: Page, cmd: string) => page.evaluate((cmd) => (window as any).__sent.findLast((c: any) => c.cmd === cmd), cmd);

async function editKeyedPrinter(page: Page) {
  await dashboard(page, { engine: engine({ printers: [keyedPrinter()], integrations: keyedIntegrations }), dialog: "printers" });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  return page.locator(".panel .panel");
}

test("a printer's saved key is never shown, is kept by a save that leaves it blank and does not hold up Save or Test", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  const key = form.getByLabel(/^API key/);
  await expect(key).toHaveValue("");
  await expect(key).toHaveAttribute("placeholder", KEPT_HINT);
  await expect(key).toHaveAccessibleDescription(KEPT_HINT);

  await form.getByRole("button", { name: "Test connection" }).click();
  expect(await sent(page, "printer.test")).toMatchObject({ id: "p1", provider: "octoprint", config: { url: "http://mk4" } });
  expect((await sent(page, "printer.test")).config).not.toHaveProperty("api_key");

  await form.getByRole("textbox", { name: "Name" }).fill("MK4S");
  await form.getByRole("button", { name: "Save", exact: true }).click();
  const saved = await sent(page, "printer.update");
  expect(saved.patch).toEqual({ name: "MK4S", config: { url: "http://mk4" } });
});

test("a key typed over a saved one is sent, then forgotten by the form once the hub has it", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  const key = form.getByLabel(/^API key/);
  await key.fill("fresh");
  await expect(form.getByRole("button", { name: "Remove the stored API key" })).toBeHidden();
  await form.getByRole("button", { name: "Save", exact: true }).click();
  const saved = await sent(page, "printer.update");
  expect(saved.patch.config).toEqual({ url: "http://mk4", api_key: "fresh" });

  await emit(page, { event: "state", ...engine({ printers: [keyedPrinter()], integrations: keyedIntegrations }), req_id: saved.req_id });
  await expect(key).toHaveValue("");
  await expect(key).toHaveAttribute("placeholder", KEPT_HINT);
  await expect(form.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  await key.fill("typo");
  await key.fill("");
  await expect(form.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
});

test("clearing a saved key from the keyboard sends null and hands focus back to the field", async ({ page, browserName }) => {
  const form = await editKeyedPrinter(page);
  const key = form.getByLabel(/^API key/);
  const clear = form.getByRole("button", { name: "Remove the stored API key" });
  await key.focus();
  await page.keyboard.press(browserName === "webkit" ? "Alt+Tab" : "Tab");
  await expect(clear).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(clear).toBeHidden();
  await expect(key).toBeFocused();
  await expect(key).toHaveAccessibleDescription("Will be removed on Save");

  await form.getByRole("button", { name: "Save", exact: true }).click();
  expect((await sent(page, "printer.update")).patch.config).toEqual({ url: "http://mk4", api_key: null });
});

test("the clear control is a full touch target on a phone", async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  const form = await editKeyedPrinter(page);
  const box = await form.getByRole("button", { name: "Remove the stored API key" }).boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await context.close();
});

test("a printer save the hub refuses says why beside the form and keeps what was typed", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  await form.getByRole("textbox", { name: "Address" }).fill("http://mk3");
  await form.getByLabel(/^API key/).fill("again");
  await form.getByRole("button", { name: "Save", exact: true }).click();
  const refusal = "the printer did not answer";
  await emit(page, { event: "error", message: refusal, req_id: (await sent(page, "printer.update")).req_id });
  await expect(form.getByRole("alert")).toHaveText(refusal);
  await expect(form.getByRole("textbox", { name: "Address" })).toHaveValue("http://mk3");

  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(form.getByRole("alert")).toBeHidden();
  expect((await lastSent(page, "printer.update")).patch.config).toEqual({ url: "http://mk3", api_key: "again" });
});

test("a moved printer address asks for the saved key again and the whole address, and sends neither half-typed", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  const save = form.getByRole("button", { name: "Save", exact: true });
  const key = form.getByLabel(/^API key/);
  await form.getByRole("textbox", { name: "Address" }).fill("http://mk3");
  await expect(form.getByText("The saved address may hide a login or key, so type the whole address.")).toBeVisible();
  await expect(key).toHaveAttribute("placeholder", "Type it again, the address changed");
  await expect(form.getByRole("button", { name: "Remove the stored API key" })).toBeHidden();
  await expect(form.getByText("Retype API key, since the address changed.")).toBeVisible();
  await expect(save).toBeDisabled();

  await key.fill("again");
  await expect(save).toBeEnabled();
});

test("a printer address that shows [redacted] is only saved untouched", async ({ page }) => {
  await dashboard(page, {
    engine: engine({ printers: [keyedPrinter({ config: { url: "http://mk4/?apikey=[redacted]" }, secrets_set: [] })], integrations: keyedIntegrations }),
    dialog: "printers",
  });
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  const form = page.locator(".panel .panel");
  const address = form.getByRole("textbox", { name: "Address" });
  const save = form.getByRole("button", { name: "Save", exact: true });
  await form.getByRole("textbox", { name: "Name" }).fill("MK4S");
  await expect(save).toBeEnabled();

  await address.fill("http://mk5/?apikey=[redacted]");
  await expect(form.getByText("The address still has [redacted] in it. Type the whole address.")).toBeVisible();
  await expect(save).toBeDisabled();
  await address.fill("http://mk5/?apikey=abc");
  await expect(save).toBeEnabled();
});

const ntfy = {
  id: "ntfy", label: "ntfy", docs_url: "",
  schema: { properties: { url: { title: "Topic address", secret: true }, priority: { title: "Priority" } }, required: ["url"] },
};
const withSavedChannel = (over = {}) =>
  engine({ notifiers: [ntfy], settings: { ...engine().settings, notifiers: { ntfy: { priority: "high" } } }, secrets_set: { notifiers: { ntfy: ["url"] }, mqtt: [] }, ...over });

test("the alerts step reads as done from a channel's saved secret alone", async ({ page }) => {
  const bare = { cameras: [], monitors: [], notifiers: [ntfy] };
  await dashboard(page, { engine: engine({ ...bare, secrets_set: { notifiers: { ntfy: ["url"] }, mqtt: [] } }) });
  await expect(page.getByRole("button", { name: "Open Connect a printer", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Set up alerts", exact: true })).toBeHidden();

  await emit(page, { event: "state", ...engine(bare) });
  await expect(page.getByRole("button", { name: "Open Set up alerts", exact: true })).toBeVisible();
});

test("a channel's saved secret is kept by a save or a test that leaves it blank, replaced when typed and removed by Clear", async ({ page }) => {
  await dashboard(page, { engine: withSavedChannel(), dialog: "settings" });
  const address = page.getByLabel(/^Topic address/);
  await expect(address).toHaveValue("");
  await expect(address).toHaveAccessibleDescription(KEPT_HINT);

  await page.getByRole("button", { name: "Send test alert" }).click();
  expect(await sent(page, "notify.test")).toMatchObject({ provider: "ntfy", config: { priority: "high" } });
  await emit(page, { event: "notify_test", provider: "ntfy", ok: true, req_id: (await sent(page, "notify.test")).req_id });

  await page.getByRole("textbox", { name: "Priority" }).fill("low");
  await page.getByRole("button", { name: "Save channels" }).click();
  expect((await lastSent(page, "settings.update")).patch).toEqual({ notifiers: { ntfy: { priority: "low" } } });
  const lowered = withSavedChannel({ settings: { ...engine().settings, notifiers: { ntfy: { priority: "low" } } } });
  await emit(page, { event: "state", ...lowered, req_id: (await lastSent(page, "settings.update")).req_id });

  await address.fill("https://ntfy.sh/new");
  await page.getByRole("button", { name: "Save channels" }).click();
  expect((await lastSent(page, "settings.update")).patch.notifiers.ntfy).toEqual({ priority: "low", url: "https://ntfy.sh/new" });
  await emit(page, { event: "state", ...lowered, req_id: (await lastSent(page, "settings.update")).req_id });
  await expect(address).toHaveValue("");

  await page.getByRole("button", { name: "Remove the stored Topic address" }).click();
  await page.getByRole("button", { name: "Save channels" }).click();
  expect((await lastSent(page, "settings.update")).patch.notifiers.ntfy).toEqual({ priority: "low", url: null });
});

test("a channel switched off and on again keeps what was typed and its saved secret", async ({ page }) => {
  await dashboard(page, { engine: withSavedChannel(), dialog: "settings" });
  const priority = page.getByRole("textbox", { name: "Priority" });
  await priority.fill("low");
  await page.getByRole("switch", { name: "ntfy" }).click();
  await expect(priority).toBeHidden();
  await page.getByRole("switch", { name: "ntfy" }).click();

  await expect(priority).toHaveValue("low");
  await expect(page.getByLabel(/^Topic address/)).toHaveAccessibleDescription(KEPT_HINT);
});

test("a channel's test result goes when its form is edited", async ({ page }) => {
  await dashboard(page, { engine: withSavedChannel(), dialog: "settings" });
  await page.getByRole("button", { name: "Send test alert" }).click();
  await emit(page, { event: "notify_test", provider: "ntfy", ok: true, req_id: (await sent(page, "notify.test")).req_id });
  await expect(page.getByText("sent", { exact: true })).toBeVisible();

  await page.getByRole("textbox", { name: "Priority" }).fill("low");
  await expect(page.getByText("sent", { exact: true })).toBeHidden();
});

test("the broker form refuses an empty host and asks for the password again when the address moves", async ({ page }) => {
  const broker = { enabled: true, host: "broker.lan", username: "pg" };
  const state = engine({ settings: { ...engine().settings, mqtt: broker }, secrets_set: { notifiers: {}, mqtt: ["password"] } });
  await dashboard(page, { engine: state, dialog: "settings", settingsTab: "mqtt" });
  await page.getByRole("tab", { name: "Home Assistant" }).click();
  const save = page.getByRole("button", { name: "Save broker settings" });
  const host = page.getByLabel("Broker host");
  const password = page.getByLabel("Password", { exact: true });
  await expect(save).toBeEnabled();

  await host.fill("");
  await expect(page.getByText("Enter the broker host.")).toBeVisible();
  await expect(save).toBeDisabled();

  await host.fill("other.lan");
  await expect(password).toHaveAttribute("placeholder", "Type it again, the address changed");
  await expect(page.getByText("Retype Password, since the address changed.")).toBeVisible();
  await expect(save).toBeDisabled();
  await password.fill("hunter2");
  await expect(save).toBeEnabled();
});

test("the broker password follows the port in effect, so typing it or switching TLS keeps it and another port asks again", async ({ page }) => {
  const broker = { enabled: true, host: "broker.lan", tls: true, username: "pg" };
  const state = engine({ settings: { ...engine().settings, mqtt: broker }, secrets_set: { notifiers: {}, mqtt: ["password"] } });
  await dashboard(page, { engine: state, dialog: "settings", settingsTab: "mqtt" });
  await page.getByRole("tab", { name: "Home Assistant" }).click();
  const save = page.getByRole("button", { name: "Save broker settings" });
  const port = page.getByLabel("Broker port");
  const retype = page.getByText("Retype Password, since the address changed.");

  await port.fill("8883");
  await expect(retype).toBeHidden();
  await expect(save).toBeEnabled();

  await port.fill("1883");
  await expect(retype).toBeVisible();
  await expect(save).toBeDisabled();

  await port.fill("");
  await page.getByText("Use TLS").click();
  await expect(retype).toBeHidden();
  await expect(save).toBeEnabled();
});

test("the broker password is kept by an unrelated broker edit, replaced when typed and removed by Clear", async ({ page }) => {
  const broker = { enabled: true, host: "broker.lan", port: 1883, username: "pg" };
  const state = engine({ settings: { ...engine().settings, mqtt: broker }, secrets_set: { notifiers: {}, mqtt: ["password"] } });
  await dashboard(page, { engine: state, dialog: "settings", settingsTab: "mqtt" });
  await page.getByRole("tab", { name: "Home Assistant" }).click();
  const password = page.getByLabel("Password", { exact: true });
  await expect(password).toHaveValue("");
  await expect(password).toHaveAttribute("placeholder", KEPT_HINT);
  await expect(password).toHaveAccessibleDescription(KEPT_HINT);

  await page.getByText("Use TLS").click();
  await page.getByRole("button", { name: "Save broker settings" }).click();
  expect((await lastSent(page, "settings.update")).patch).toEqual({ mqtt: { ...broker, tls: true } });
  await emit(page, { event: "state", ...state, req_id: (await lastSent(page, "settings.update")).req_id });

  await password.fill("hunter2");
  await page.getByRole("button", { name: "Save broker settings" }).click();
  expect((await lastSent(page, "settings.update")).patch.mqtt.password).toBe("hunter2");
  await emit(page, { event: "state", ...state, req_id: (await lastSent(page, "settings.update")).req_id });
  await expect(password).toHaveValue("");

  await page.getByRole("button", { name: "Remove the stored password" }).click();
  await page.getByRole("button", { name: "Save broker settings" }).click();
  expect((await lastSent(page, "settings.update")).patch.mqtt.password).toBeNull();
});

test("an auto-saved setting sends only itself, never the channels, the broker or the saved secret names", async ({ page }) => {
  const state = withSavedChannel({ settings: { ...engine().settings, notifiers: { ntfy: {} }, mqtt: { enabled: true, host: "broker.lan" } }, secrets_set: { notifiers: { ntfy: ["url"] }, mqtt: ["password"] } });
  await dashboard(page, { engine: state });
  await page.evaluate(() => {
    const store = (window as any).__pg.getState();
    store.updateSettings({ fault_grace_s: 300 });
    store.flushUpdates();
  });
  expect(await sent(page, "settings.update")).toMatchObject({ patch: { fault_grace_s: 300 } });
  expect(Object.keys((await sent(page, "settings.update")).patch)).toEqual(["fault_grace_s"]);
  const shown = await page.evaluate(() => (window as any).__pg.getState().engine);
  expect(shown.secrets_set).toEqual({ notifiers: { ntfy: ["url"] }, mqtt: ["password"] });
  expect(shown.settings.mqtt).toEqual({ enabled: true, host: "broker.lan" });
});

test("a camera with no access code and a scrubbed address still lists", async ({ page }) => {
  const cameras = [camera({ source: { kind: "bambu", host: "192.168.1.9" }, printer_id: "p1" }), camera({ id: "c2", name: "Shed", source: { kind: "rtsp", url: "rtsp://shed/live" } })];
  await dashboard(page, { engine: engine({ cameras }), dialog: "cameras" });
  await expect(page.getByText("bambu://192.168.1.9").first()).toBeVisible();
  await expect(page.getByText("rtsp://shed/live").first()).toBeVisible();
});
