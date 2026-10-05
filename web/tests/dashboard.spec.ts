import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

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

async function hub(page: Page, onCommand: (command: any, socket: WebSocketRoute) => void = () => {}) {
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
    socket.send(JSON.stringify({ event: "state", ...engine() }));
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

test("closing settings part way through a theme puts the saved theme back", async ({ page }) => {
  await dashboard(page, { dialog: "settings", settingsTab: "appearance" });
  await page.getByRole("button", { name: "+ New" }).click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Switch theme" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-glass", "");
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
