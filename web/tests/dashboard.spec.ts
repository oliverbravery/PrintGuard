import { expect, test, type Page } from "@playwright/test";
import { camera, dashboard, emit, engine, hub, monitor, pastDoublePress, review, sent } from "./fixtures";
import { zipSync } from "fflate";

const EMPTY_ZIP = "UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==";

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

test("picking a detection model in Settings sends it and marks it in use", async ({ page }) => {
  const { commands } = await hub(page, () => {}, engine({ settings: { ...engine().settings, model: "standard", inference_runtime: "auto" } }), "/settings/detection");
  const light = page.getByRole("group", { name: "Detection model" }).getByRole("button", { name: /^Light/ });
  await light.click();
  await expect.poll(() => commands.filter((c) => c.cmd === "settings.update").map((c) => c.patch)).toEqual([{ model: "light" }]);
  await expect(light).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("group", { name: "Failed prints caught against latency for each model" })).toBeVisible();
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
  const { sockets } = await hub(page, undefined, engine(), "/monitors/m1/edit");
  await page.routeWebSocket(/\/api\/ws$/, (socket) => void socket.close());
  await sockets[0].close();
  await expect(page.getByRole("status").getByText("reconnecting")).toBeVisible();
  const main = page.getByRole("main");
  await main.getByRole("button", { name: "Delete monitor" }).click();
  await pastDoublePress(page);
  await main.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByRole("status").filter({ hasText: "wasn't sent" })).toBeVisible();
  await expect(main.getByRole("button", { name: "Delete monitor" })).toBeEnabled();
  expect(await page.evaluate(() => (window as any).__pg.getState().pending)).toEqual({});
});

test("deleting a monitor from its settings goes back to the monitors and brings the other feeds back", async ({ page }) => {
  const cameras = [camera(), camera({ id: "c2", name: "Garage" })];
  const voron = monitor({ id: "m2", name: "Voron", camera_id: "c2" });
  await hub(
    page,
    (command, socket) => {
      if (command.cmd !== "monitor.remove") return;
      socket.send(JSON.stringify({ event: "state", ...engine({ cameras, monitors: [voron] }), req_id: command.req_id }));
    },
    engine({ cameras, monitors: [monitor(), voron] }),
    "/monitors/m1/edit",
  );
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "Prusa settings" })).toBeVisible();
  const feedRestarted = page.waitForRequest(/\/hls\/c2\//);
  await main.getByRole("button", { name: "Delete monitor" }).click();
  await pastDoublePress(page);
  await main.getByRole("button", { name: "Confirm" }).click();

  await expect(page).toHaveURL(/#\/$/);
  await expect(main.getByRole("heading", { name: "Voron" })).toBeVisible();
  await feedRestarted;
});

test("a history or review page goes back when what it shows is removed elsewhere", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 0, alerts: 0 })] }) }, "/monitors/m1/review/r1");
  await expect(page.getByRole("heading", { level: 1, name: "Prusa review" })).toBeVisible();
  await emit(page, { event: "state", ...engine() });
  await expect(page).toHaveURL(/#\/monitors\/m1$/);

  await page.evaluate(() => (location.hash = "#/monitors/m1/history"));
  await expect(page.getByRole("heading", { level: 1, name: "Prusa history" })).toBeVisible();
  await emit(page, { event: "state", ...engine({ monitors: [] }) });
  await expect(page).toHaveURL(/#\/$/);
});


test("a monitor asks about its last print only", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review(), review({ id: "r2", status: "dismissed" })] }) });
  await expect(page.getByRole("heading", { name: "Prusa" })).toBeVisible();
  await expect(page.getByText(/from the last print/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: /^Review/ })).toHaveCount(0);

  await emit(page, { event: "state", ...engine({ reviews: [review({ status: "dismissed" }), review({ id: "r2", frames: 7 })] }) });
  await expect(page.getByText("7 frames from the last print")).toBeVisible();
  await page.getByRole("link", { name: "Review 7 frames from Prusa" }).click();
  await expect(page).toHaveURL(/#\/monitors\/m1\/review\/r2$/);
});

test("one kept frame is not called frames on the monitor or in its review", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 1 })] }) });
  await expect(page.getByText("1 frame from the last print")).toBeVisible();
  await page.getByRole("link", { name: "Review 1 frame from Prusa" }).click();
  await expect(page.getByRole("main").getByText("PrintGuard kept 1 frame from this print.")).toBeVisible();
});

test("the review's answers sit in a group named by their question and the printer model has a name", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review()] }) }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  const question = main.getByRole("group", { name: "Did this print finish without any problems?" });
  await expect(question.getByRole("radio")).toHaveCount(2);
  await expect(question.getByRole("radio", { name: "No, something went wrong" })).toBeVisible();

  await question.getByRole("radio", { name: "Yes" }).check();
  await expect(main.getByRole("textbox", { name: "Printer model" })).toBeVisible();
});

test("a review answered before its frames arrive still marks the alert frames, and a frame left out is not sent", async ({ page }) => {
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "review.get").length);
  const picture = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
  await dashboard(page, { engine: engine({ reviews: [review()] }), snapshotCache: { a1: picture, s1: picture, s2: picture } }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  await expect(main.getByText("PrintGuard kept 3 frames from this print.")).toBeVisible();
  await expect.poll(asked).toBeGreaterThan(0);
  const onOpening = await asked();
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(asked).toBe(onOpening + 1);

  await main.getByRole("radio", { name: "No, something went wrong" }).check();
  const frames = [
    { id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 },
    { id: "s1", ts: 120, score: 0.1, kind: "spaced", size: 1 },
    { id: "s2", ts: 180, score: 0.1, kind: "spaced", size: 1 },
  ];
  await emit(page, { event: "review", ...review(), frames });
  await expect(main.getByRole("button", { name: /marked Real failure/ })).toHaveCount(1);
  await expect(main.getByRole("button", { name: /marked Good/ })).toHaveCount(2);

  await main.getByRole("button", { name: /^Don't send/ }).nth(1).click();
  await expect(main.getByRole("button", { name: /marked Good/ })).toHaveCount(1);
  await main.getByRole("button", { name: "Send 2 frames" }).click();
  expect(await sent(page, "review.send")).toMatchObject({ id: "r1", failures: ["a1"], removed: ["s1"] });

  await main.getByRole("link", { name: "Monitors" }).click();
  await expect(page).toHaveURL(/#\/monitors\/m1$/);
  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().snapshotCache)).toEqual({});
});

const picked = [
  { id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 },
  { id: "s1", ts: 120, score: 0.1, kind: "spaced", size: 1 },
  { id: "s2", ts: 180, score: 0.1, kind: "spaced", size: 1 },
];
const timeline = Array.from({ length: 40 }, (_, index) => [index * 5, index > 30 ? 0.8 : 0.1]);
const recorded = (over = {}) => review({ recording: { frames: 40, bytes: 98 * 1024 * 1024, expires: 7 * 86_400 }, ...over });

test("every frame of a review can be cleared at once and one added from the recording sends alone", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [recorded()] }) }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  await main.getByRole("radio", { name: "Yes" }).check();
  await emit(page, { event: "review", ...recorded(), frames: picked, timeline });

  await main.getByRole("button", { name: "Clear all" }).click();
  await expect(main.getByRole("button", { name: "Send 0 frames" })).toBeDisabled();
  await expect(main.getByText("No frames picked. Add some from the recording.")).toBeVisible();

  await main.getByRole("button", { name: "Add as good" }).click();
  expect(await sent(page, "review.add")).toMatchObject({ id: "r1", index: 39, label: "good" });
  const added = { id: "d1", ts: 195, score: 0.8, kind: "added", label: "good", size: 1 };
  await emit(page, { event: "review", ...recorded({ frames: 4 }), frames: [...picked, added], timeline });
  await main.getByRole("button", { name: "Send 1 frame" }).click();
  expect(await sent(page, "review.send")).toMatchObject({ id: "r1", failures: [], removed: ["a1", "s1", "s2"] });
});

test("a reviewer scrubs through the print's recording and adds a frame PrintGuard didn't pick", async ({ page }) => {
  const picture = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
  await dashboard(page, { engine: engine({ reviews: [recorded()] }), snapshotCache: { "r1:39": picture } }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  await main.getByRole("radio", { name: "No, something went wrong" }).check();
  await emit(page, { event: "review", ...recorded(), frames: picked, timeline });
  await expect(main.getByText("Alert frames are marked as real failures.", { exact: false })).toBeVisible();
  await expect(main.getByText("3 of 60")).toBeVisible();

  const scrubber = main.getByRole("slider", { name: "Whole print" });
  await expect(scrubber).toHaveAttribute("aria-valuetext", "0:03:15 in · 80%");
  await expect(main.getByRole("img", { name: "The print 0:03:15 in, scored 80%" })).toBeVisible();
  await scrubber.focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => lastSent(page, "recording.frame")).toMatchObject({ id: "r1", index: 38 });
  await expect(main.getByRole("status").filter({ hasText: "loading" })).toBeVisible();
  await main.getByRole("button", { name: "Previous frame" }).click();
  await expect(scrubber).toHaveAttribute("aria-valuetext", "0:03:05 in · 80%");

  await main.getByRole("button", { name: "Add as failure" }).click();
  expect(await sent(page, "review.add")).toMatchObject({ id: "r1", index: 37, label: "failure" });
  const added = { id: "d1", ts: 185, score: 0.8, kind: "added", label: "failure", size: 1 };
  await emit(page, { event: "review", ...recorded({ frames: 4 }), frames: [...picked, added], timeline });
  await expect(main.getByText("4 of 60")).toBeVisible();
  await expect(main.getByRole("button", { name: "Add as failure" })).toBeDisabled();
  await expect(main.getByRole("button", { name: /^Frame 4 of 4 at .* marked Failure/ })).toContainText("added ·");

  await main.getByRole("button", { name: "Send 4 frames" }).click();
  expect(await sent(page, "review.send")).toMatchObject({ id: "r1", failures: ["a1", "d1"], removed: [] });
});

test("a print holding more than a day's frames can't be sent until enough are left out", async ({ page }) => {
  const frames = Array.from({ length: 61 }, (_, index) => ({ id: `s${index}`, ts: index, score: 0.1, kind: "spaced", size: 1 }));
  await dashboard(page, { engine: engine({ reviews: [recorded({ frames: 61 })] }) }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  await main.getByRole("radio", { name: "Yes" }).check();
  await emit(page, { event: "review", ...recorded({ frames: 61 }), frames, timeline });

  await expect(main.getByText("61 of 60")).toBeVisible();
  await expect(main.getByRole("status").filter({ hasText: "You can send 60 frames a day. Leave 1 out to send this print." })).toBeVisible();
  await expect(main.getByRole("button", { name: "Send 61 frames" })).toBeDisabled();
  await expect(main.getByRole("button", { name: "Add as good" })).toBeDisabled();
  await main.getByRole("button", { name: /^Don't send/ }).first().click();
  await expect(main.getByRole("status").filter({ hasText: "Leave one out to add another." })).toBeVisible();
  await expect(main.getByRole("button", { name: "Send 60 frames" })).toBeEnabled();
});

test("the review says how big the print's recording is and when it goes, and leads to its storage settings", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [recorded()] }) }, "/monitors/m1/review/r1");
  const main = page.getByRole("main");
  await expect(main.getByText(/This print's recording is 98 MB and is deleted on/)).toBeVisible();
  await main.getByRole("link", { name: "Manage storage" }).click();
  await expect(page).toHaveURL(/#\/settings\/storage$/);
  await expect(page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Storage" })).toHaveAttribute("aria-current", "page");
});

test("the storage tab lists each recording with its size and deletes one or all of them", async ({ page }) => {
  const reviews = [recorded({ bytes: 2 * 1024 * 1024 }), recorded({ id: "r2", ended: null, status: "running", recording: { frames: 3, bytes: 1024 * 1024, expires: null } })];
  await dashboard(page, { engine: engine({ reviews }) }, "/settings/storage");
  const list = page.getByRole("list", { name: "Recordings" });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("listitem").first()).toContainText("98 MB");
  await expect(list.getByRole("listitem").first()).toContainText("waiting for review");
  await expect(list.getByRole("listitem").nth(1)).toContainText("recording now");
  await expect(page.getByText("99 MB")).toBeVisible();
  await expect(page.getByText("2.0 MB")).toBeVisible();

  await list.getByRole("listitem").nth(1).getByRole("button", { name: /^Delete the recording of Prusa/ }).click();
  await pastDoublePress(page);
  await list.getByRole("listitem").nth(1).getByRole("button", { name: /^Delete the recording of Prusa/ }).click();
  await expect.poll(() => sent(page, "recording.delete")).toMatchObject({ ids: ["r2"] });
  await page.getByRole("button", { name: "Delete all recordings" }).click();
  await pastDoublePress(page);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect.poll(() => lastSent(page, "recording.delete")).toMatchObject({ ids: ["r1", "r2"] });

  await page.getByRole("combobox", { name: "Recordings" }).selectOption({ label: "Keep each print's recording for 14 days" });
  await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
  await expect.poll(() => lastSent(page, "settings.update")).toMatchObject({ patch: { recording_days: 14 } });
});

test("a review frame shows whole whatever its shape and any frame opens full size", async ({ page }) => {
  const square = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>')}`;
  const frames = [
    { id: "s1", ts: 60, score: 0.1, kind: "spaced", size: 1 },
    { id: "a1", ts: 120, score: 0.9, kind: "alert", action: "pause", size: 1 },
  ];
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 2 })] }), snapshotCache: { s1: square, a1: square } }, "/monitors/m1/review/r1");
  await emit(page, { event: "review", ...review({ frames: 2 }), frames });
  const main = page.getByRole("main");
  await main.getByRole("radio", { name: "Yes" }).check();
  const pictures = main.getByRole("listitem").locator("img");
  await expect(pictures).toHaveCount(2);
  expect(await pictures.first().evaluate((img) => getComputedStyle(img).objectFit)).toBe("contain");

  await main.getByRole("button", { name: /^Enlarge frame 1 of 2 at/ }).click();
  const enlarged = page.getByRole("dialog", { name: /10%/ });
  await expect(enlarged.locator("img")).toHaveAttribute("src", square);
  await page.keyboard.press("Escape");
  await expect(enlarged).toBeHidden();
  await expect(main.getByRole("heading", { level: 1, name: "Prusa review" })).toBeVisible();
});

test("opening the history asks only for the snapshots near the screen", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const sheet = page.getByRole("main");
  const snaps = Array.from({ length: 90 }, (_, index) => ({ id: `s${index}`, ts: 1_700_000_000 - index, score: 0.9, action: "failed" }));
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_100, buckets: [], snaps, alerts: [], stats: {} });
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "snapshot.get").map((c: any) => c.id));
  await expect.poll(async () => (await asked()).length).toBeGreaterThan(0);
  expect((await asked()).length).toBeLessThan(30);

  await sheet.getByRole("button", { name: /Snapshot at 90% risk/ }).last().scrollIntoViewIfNeeded();
  await expect.poll(asked).toContain("s89");
});

test("a minute of history on its own is drawn across its width, not as a dot", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const chart = page.getByRole("main").getByRole("img", { name: "Risk over time" });
  const bucket = (t: number) => ({ t, n: 10, sum: 4.5, min: 0.4, max: 0.5, defects: 10, watched: 60 });
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_200, buckets: [bucket(1_699_999_980), bucket(1_700_000_100)], snaps: [], alerts: [], stats: {} });

  await expect(chart.locator("path")).toHaveCount(4);
  const widths = await chart.locator("path").evaluateAll((paths) => paths.map((path) => path.getBoundingClientRect().width));
  for (const width of widths) expect(width).toBeGreaterThan(100);
});

test("a history chart spanning more than a day dates the ends of its axis", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const sheet = page.getByRole("main");
  const bucket = (t: number) => ({ t, n: 10, sum: 4.5, min: 0.4, max: 0.5, defects: 0, watched: 60 });
  const twoDays = 2 * 86_400;
  const ends = sheet.getByRole("img", { name: "Defect frames per period" }).locator("xpath=following-sibling::div[1]/span");
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_000 + twoDays, buckets: [bucket(1_700_000_000), bucket(1_700_000_000 + twoDays)], snaps: [], alerts: [], stats: {} });
  await sheet.getByRole("button", { name: "all", exact: true }).click();

  const [first, last] = await ends.allTextContents();
  expect(first).not.toBe(last);
});

test("after a hub restart the alerts figure still counts the snapshots that were kept", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const snaps = [1, 2, 3].map((index) => ({ id: `s${index}`, ts: 1_700_000_000 - index, score: 0.9, action: "failed" }));
  await emit(page, { event: "history", monitor_id: "m1", now: 1_700_000_100, buckets: [], snaps, alerts: [], stats: { alerts: 0, snaps: 3 } });
  await expect(page.getByText("alerts", { exact: true }).locator("xpath=following-sibling::div")).toHaveText("3");
});

test("a failure card at the narrowest phone keeps its time and score inside the card", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await dashboard(page, { engine: engine({ reviews: [review({ frames: 1 })] }) }, "/monitors/m1/review/r1");
  await emit(page, { event: "review", ...review({ frames: 1 }), frames: [{ id: "a1", ts: 120, score: 0.9, kind: "alert", action: "pause", size: 1 }] });
  const main = page.getByRole("main");
  await main.getByRole("radio", { name: "No, something went wrong" }).check();

  const card = main.getByRole("listitem").filter({ hasText: "Real failure" });
  const box = (await card.boundingBox())!;
  const score = (await card.getByText(/90%/).boundingBox())!;
  expect(score.x).toBeGreaterThanOrEqual(box.x);
  expect(score.x + score.width).toBeLessThanOrEqual(box.x + box.width);
});

test("sheets and the page keep clear of the right safe area", async ({ page }) => {
  await dashboard(page);
  const insets = await page.evaluate(() => {
    const rules = (list: CSSRuleList): CSSRule[] => [...list].flatMap((rule) => ("cssRules" in rule ? [rule, ...rules((rule as CSSGroupingRule).cssRules)] : [rule]));
    const all = [...document.styleSheets].flatMap((sheet) => rules(sheet.cssRules));
    return [".app", ".sheet"].map((selector) => all.some((rule) => rule instanceof CSSStyleRule && rule.selectorText === selector && rule.cssText.includes("safe-area-inset-right")));
  });
  expect(insets).toEqual([true, true]);
});

test("review frames whose pictures were lost to a reconnect are asked for again", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review()] }) }, "/monitors/m1/review/r1");
  await emit(page, { event: "review", ...review(), frames: [{ id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 }] });
  await page.getByRole("main").getByRole("radio", { name: "Yes" }).check();
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "snapshot.get").length);
  await expect.poll(asked).toBeGreaterThan(0);
  const before = await asked();

  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(asked).toBeGreaterThan(before);
});

test("the history page says when it has not loaded, and breaks its line between prints", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const sheet = page.getByRole("main");
  await expect(sheet.getByText("loading history")).toHaveCount(2);
  await expect(sheet.getByText("No alerts have fired yet")).toBeHidden();

  const now = 1_700_000_040;
  const bucket = (t: number) => ({ t, min: 0.1, max: 0.3, sum: 0.4, n: 2, defects: 0 });
  const buckets = [now - 3000, now - 2940, now - 600, now - 540].map(bucket);
  await emit(page, { event: "history", monitor_id: "m1", now, buckets, snaps: [], alerts: [], stats: {} });
  await expect(sheet.getByText("No alerts have fired yet")).toBeVisible();
  await expect(sheet.getByRole("img", { name: "Risk over time" }).locator('path[fill="none"]')).toHaveCount(2);
});

test("the history page asks for the rollup once, then again only when an alert is kept", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/history");
  const asked = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "history.get").length);
  const sheet = page.getByRole("main");
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

test("a camera that cannot open says why in the camera list", async ({ page }) => {
  const reason = "no decoder for this stream";
  await dashboard(page, { engine: engine({ cameras: [camera({ online: false, in_use: false, reason })] }) }, "/cameras");
  await expect(page.getByRole("link", { name: new RegExp(reason) })).toBeVisible();
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
  const rows = page.getByRole("main").getByRole("listitem");
  await expect(rows).toHaveCount(2);
  for (const row of await rows.all()) {
    await expect(row).not.toContainText("5.0");
    await expect(row.getByRole("img", { name: "risk unknown" })).toBeVisible();
  }
  await expect(rows.nth(0)).toContainText("standby");
  await expect(rows.nth(1)).toContainText("off");
});

test("two layout edits in a row both hold through a stale tick and go out as one save", async ({ page }) => {
  await dashboard(page);
  await page.evaluate(() => {
    const state = (window as any).__pg.getState();
    state.mutateLayout((section: any) => ({ ...section, pinned: ["m1"] }));
    state.mutateLayout((section: any) => ({ ...section, hidden: ["m9"] }));
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
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }) });
  await page.getByRole("tab", { name: "Preheat" }).click();
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
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }) });
  await page.getByRole("tab", { name: "Preheat" }).click();
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

test("a monitor name or heater target typed and left by going elsewhere is still saved", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })] }) }, "/monitors/m1/edit");
  await page.getByRole("main").getByRole("textbox", { name: "Name" }).fill("Bench");
  await page.getByRole("main").getByRole("link", { name: "Monitors" }).click();
  await page.getByRole("tab", { name: "Preheat" }).click();
  await page.getByRole("spinbutton", { name: "nozzle target" }).fill("215");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /Prints/ }).click();
  await expect(page).toHaveURL(/#\/prints$/);

  const commands = () => page.evaluate(() => (window as any).__sent.map((c: any) => [c.cmd, c.patch ?? c.nozzle]));
  expect(await commands()).toEqual(expect.arrayContaining([["monitor.update", { name: "Bench" }], ["printer.heat", 215]]));
  expect(await commands()).toHaveLength(2);
});

test("the register form keeps what was typed when the printer is refused and opens the printer once it is added", async ({ page }) => {
  await dashboard(page, {}, "/printers/new");
  await page.getByRole("combobox", { name: "Printer service" }).selectOption("octoprint");
  const name = page.getByRole("main").getByRole("textbox", { name: "Name" });
  await name.fill("Bench printer");
  const requests = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "printer.add"));

  await page.getByRole("button", { name: "Register printer" }).click();
  await emit(page, { event: "error", message: "no printer answered there", req_id: (await requests())[0].req_id });
  await expect(name).toHaveValue("Bench printer");

  await page.getByRole("button", { name: "Register printer" }).click();
  await expect.poll(async () => (await requests()).length).toBe(2);
  const added = { id: "p1", name: "Bench printer", provider: "octoprint", config: {}, online: true, device_state: null };
  await emit(page, { event: "state", ...engine({ printers: [added] }), req_id: (await requests())[1].req_id });
  await expect(page).toHaveURL(/#\/printers\/p1$/);
  await expect(page.getByRole("heading", { name: "Bench printer" })).toBeVisible();
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
  }, "/settings/plugins");
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
  await dashboard(page, { engine: withPlugins([demoPlugin({ manifest: { ...demoPlugin().manifest, secrets: { api_key: "Your key" } } })]) }, "/settings/plugins");
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
  expect(commands.find((c) => c.cmd === "plugin.update").patch).toEqual({ store: { written: { picked: ["bench"] }, removed: [] } });
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
  const tap = page.getByRole("region", { name: /selected monitor$/ }).getByRole("button", { name: "Tap to play" });
  const play = page.locator("main li").getByRole("button", { name: "Play", exact: true });
  await expect(tap).toBeVisible();
  await expect(play).toBeVisible();

  await tap.click();
  await expect(tap).toBeHidden();
  await play.click();
  await expect(play).toBeHidden();
  expect(new URL(page.url()).hash).toBe("#/");
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
  await expect.poll(() => starts).toBe(2);

  await float(true);
  await cover("report");
  await hide(true);
  await page.waitForTimeout(300);
  expect(await attached()).toBe(true);
  expect(starts).toBe(2);

  await float(false);
  await expect.poll(attached).toBe(false);
  await hide(false);
  await cover(null);
  await expect.poll(() => starts).toBe(4);
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
    const open = XMLHttpRequest.prototype.open;
    win.__aborts = 0;
    XMLHttpRequest.prototype.open = function (this: XMLHttpRequest & { url?: string }, ...args: unknown[]) {
      this.url = String(args[1]);
      return (open as (...rest: unknown[]) => void).apply(this, args);
    } as typeof open;
    XMLHttpRequest.prototype.abort = function (this: XMLHttpRequest & { url?: string }) {
      if (this.url?.startsWith("api/prints")) win.__aborts++;
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
  await expect(page.getByRole("status").filter({ hasText: "Close again to discard" })).toBeVisible();
  expect(await aborts()).toBe(1);
  await pastDoublePress(page);
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
    engine: engine({
      prints,
      printers: [{ id: "p1", name: "MK4", ...printer }, { id: "p2", name: "Mini", ...printer }],
      integrations: [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: ["gcode"], heater_control: true, schema: { properties: {} } }],
    }),
  };
};

test("the print library does not squeeze its list into a strip on a phone held sideways", async ({ page }) => {
  await page.setViewportSize({ width: 667, height: 375 });
  await dashboard(page, library([printFile({ id: "a", name: "First" }), printFile({ id: "b", name: "Second" }), printFile({ id: "c", name: "Third" })]), "/prints");
  await expect(page.getByRole("link", { name: /^(First|Second|Third) / })).toHaveCount(3);
  const squeezed = await page.evaluate(() =>
    [...document.querySelectorAll("main *")].filter(
      (el) => ["auto", "scroll"].includes(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1 && el.clientHeight < 200,
    ).length,
  );
  expect(squeezed).toBe(0);
});

test("two printers tagged in quick succession are both sent, without a printer that is gone", async ({ page }) => {
  await dashboard(page, library([printFile({ printer_ids: ["gone"] })]), "/prints");
  await expect(page.getByText("none of its printers is registered")).toBeVisible();
  await page.getByRole("button", { name: "MK4", exact: true }).click();
  await page.getByRole("button", { name: "Mini", exact: true }).click();

  await expect(page.getByRole("button", { name: "✓ MK4" })).toHaveAttribute("aria-pressed", "true");
  const lastUpdate = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "print.update").at(-1)?.patch);
  await expect.poll(lastUpdate).toEqual({ printer_ids: ["p1", "p2"] });
});

test("a printer that cannot print a file is named in the text, not only a hover title", async ({ page }) => {
  await dashboard(page, library([printFile({ id: "f3", name: "Plate", filename: "plate.3mf", ext: "3mf" })]), "/prints");

  await expect(page.getByText("MK4, Mini can't print .3mf files.")).toBeVisible();
});

test("removing or sending one file leaves the other files' buttons alone", async ({ page }) => {
  await dashboard(page, library([printFile(), printFile({ id: "f2", name: "Vase", uploaded: 0, meta: { time_s: 7190 } })]), "/prints/f1");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await pastDoublePress(page);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "Removing…" })).toBeVisible();

  await page.getByRole("link", { name: /^Vase / }).click();
  await expect(page.getByText("2h 0m", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Print", exact: true }).click();
  await page.getByRole("button", { name: "Start print" }).click();
  await expect(page.getByRole("button", { name: "Sending…" })).toBeVisible();

  await page.getByRole("link", { name: /^Benchy / }).click();
  await expect(page.getByRole("button", { name: "Print", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Removing…" })).toBeVisible();
});

test("a print only starts after the bed has been checked on the printer's camera", async ({ page }) => {
  const { engine: state } = library([printFile()]);
  await dashboard(page, { engine: { ...state, monitors: [monitor({ printer_id: "p1" })] } }, "/prints");
  await page.getByRole("button", { name: "Print", exact: true }).click();
  const check = page.getByRole("dialog", { name: "Print Benchy on MK4" });
  await expect(check.getByText("Is the build plate on and the bed clear?")).toBeVisible();
  await expect(check.locator("video")).toHaveCount(1);

  await check.getByRole("button", { name: "Cancel" }).click();
  await expect(check).toBeHidden();
  expect(await sent(page, "print.start")).toBeUndefined();

  await page.getByRole("button", { name: "Print", exact: true }).click();
  await check.getByRole("button", { name: "Start print" }).click();
  await expect(check).toBeHidden();
  expect(await sent(page, "print.start")).toMatchObject({ id: "f1", printer_id: "p1" });
});

test("a file uploaded seconds ago reads just now and an older one counts minutes", async ({ page }) => {
  const secondsAgo = (seconds: number) => Date.now() / 1000 - seconds;
  await dashboard(page, library([printFile({ uploaded: secondsAgo(5) }), printFile({ id: "f2", name: "Vase", uploaded: secondsAgo(150) })]), "/prints");
  await expect(page.getByText("just now")).toHaveCount(1);
  await expect(page.getByText("2m ago")).toHaveCount(1);
});

test("a file dropped beside the drop zone is staged, and the page stays where it is", async ({ page }) => {
  await page.route(/\/api\/prints\/inspect/, (route) => route.fulfill({ json: { meta: {}, thumbnail: true } }));
  await dashboard(page, library([]), "/prints");
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

  expect(await dropped("main h1", "text")).toEqual([false, false]);
  expect(await dropped("main h1", "file")).toEqual([true, true]);
  await expect(page.getByRole("heading", { name: "Upload stray.gcode" })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__pg.getState().staged.length)).toBe(1);
});

test("a printer test result shows only under the printer that was tested", async ({ page }) => {
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true, device_state: null };
  await dashboard(page, { engine: engine({ printers: [printer] }) }, "/printers/p1");
  await page.getByRole("button", { name: "Test connection" }).click();
  const asked = await sent(page, "printer.test");
  await emit(page, { event: "printer_test", ok: true, status: "printing", req_id: asked.req_id });
  await expect(page.getByText("ok, printing")).toHaveCount(1);

  await page.getByRole("link", { name: "+ Register a printer" }).click();
  await page.getByRole("combobox", { name: "Printer service" }).selectOption("octoprint");
  await expect(page.getByRole("button", { name: "Test connection" })).toBeVisible();
  await expect(page.getByText("ok, printing")).toHaveCount(0);
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

test("leaving settings part way through a theme puts the saved theme back", async ({ page }) => {
  await dashboard(page, {}, "/settings/appearance");
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("link", { name: "Monitors", exact: true }).click();
  await page.getByRole("button", { name: "Switch theme" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-glass", "");
});

test("a theme saved while the hub is away is sent once it is back", async ({ page }) => {
  const { sockets, commands } = await hub(page, undefined, engine(), "/settings/appearance");
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("textbox", { name: "Theme name" }).fill("Workshop");
  await sockets[0].close();
  await expect(page.getByText("reconnecting")).toBeVisible();
  await page.getByRole("button", { name: "Save theme" }).click();

  await expect(page.getByRole("textbox", { name: "Theme name" })).toBeHidden();
  await expect.poll(() => commands.filter((c) => c.cmd === "settings.update").at(-1)?.patch.themes?.[0].name, { timeout: 8000 }).toBe("Workshop");
});

test("a saved theme stays on screen through a state sent before the hub has answered it", async ({ page }) => {
  await dashboard(page, {}, "/settings/appearance");
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("textbox", { name: "Theme name" }).fill("Workshop");
  await page.getByRole("button", { name: "Save theme" }).click();
  await emit(page, { event: "state", ...engine() });
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).not.toBe("");

  const saved = await page.evaluate(() => (window as any).__pg.getState().engine.settings);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await pastDoublePress(page);
  await page.getByRole("button", { name: "Confirm" }).click();
  await emit(page, { event: "state", ...engine({ settings: saved }) });
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).toBe("");
});

test("a state that leaves the theme as it is restyles nothing, and one that changes it does", async ({ page }) => {
  await dashboard(page);
  await emit(page, { event: "state", ...engine() });
  await page.evaluate(() => {
    const win = window as any;
    win.__restyled = 0;
    const store = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key === "pg.theme") win.__restyled += 1;
      store.call(this, key, value);
    };
  });
  const restyled = () => page.evaluate(() => (window as any).__restyled);

  await emit(page, { event: "state", ...engine() });
  await emit(page, { event: "state", ...engine() });
  expect(await restyled()).toBe(0);

  await emit(page, { event: "state", ...engine({ settings: { ...engine().settings, theme: "light" } }) });
  expect(await restyled()).toBe(1);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("a theme started from dark keeps dark text on its accent", async ({ page }) => {
  await dashboard(page);
  const themed = { ...engine().settings, theme: "mine", themes: [{ id: "mine", name: "Mine", base: "dark", colors: {} }] };
  await emit(page, { event: "state", ...engine({ settings: themed }) });

  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-on-accent"))).toBe("#090908");
});

test("glass keeps status colours readable and distinct over a bright picture, blurs behind the page and forgets a picture that fails to load", async ({ page }) => {
  await dashboard(page);
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
  await expect(page.locator("main")).not.toHaveCSS("backdrop-filter", "none");

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
  await dashboard(page, { createdToken: { name: "ci", secret: "pg_once" } }, "/settings/api");
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
  await dashboard(page, { engine: engine({ monitors: [monitor({ consecutive: 20 })] }) }, "/monitors/m1");
  await page.getByRole("tab", { name: "Tune" }).click();
  await expect(page.getByRole("slider", { name: "Consecutive detections to alert" })).toHaveValue("20");

  await page.evaluate(() => (location.hash = "#/cameras/c1"));
  const rate = page.getByRole("slider", { name: "Detection rate" });
  await rate.fill("10");
  await rate.fill("30");
  const lastPatch = () => page.evaluate(() => (window as any).__sent.filter((c: any) => c.cmd === "camera.update").at(-1)?.patch);
  await expect.poll(lastPatch).toEqual({ detect_fps: 60 });
});

test("a camera form opens the camera once it is registered, and its fields are named", async ({ page }) => {
  await dashboard(page, {}, "/cameras/new");
  await page.getByRole("textbox", { name: "Name" }).fill("Garage");
  const address = page.getByRole("textbox", { name: "Stream URL" });
  await address.fill("rtsp://garage/stream");
  await page.getByRole("button", { name: "Register stream" }).click();
  const { req_id } = await sent(page, "camera.add");
  await emit(page, { event: "state", req_id, ...engine({ cameras: [camera(), camera({ id: "c2", name: "Garage" })] }) });
  await expect(page.getByRole("heading", { name: "Garage", level: 2 })).toBeVisible();
  await expect(page).toHaveURL(/#\/cameras\/c2$/);
  await expect(address).toHaveCount(0);

  await page.evaluate(() => (window as any).__pg.setState({ dialog: "monitor" }));
  await expect(page.getByRole("combobox", { name: "Camera" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Printer" })).toBeVisible();
});

test("Enter in a camera's name or address registers it", async ({ page }) => {
  await dashboard(page, {}, "/cameras/new");
  await page.getByRole("textbox", { name: "Stream URL" }).fill("rtsp://garage/stream");
  await page.getByRole("textbox", { name: "Name" }).press("Enter");
  expect(await sent(page, "camera.add")).toMatchObject({ name: "Stream", source: { kind: "url", url: "rtsp://garage/stream" } });
});

test("a camera's address is shown without its password, and an idle one reads idle", async ({ page }) => {
  const source = { kind: "url", url: "rtsp://admin:p@ss/w0rd@cam.local/stream?token=1" };
  await dashboard(page, { engine: engine({ cameras: [camera({ source, in_use: false })] }) }, "/cameras/c1");
  const main = page.locator("main");

  await expect(main.getByText("rtsp://cam.local/stream?token=1")).toHaveCount(2);
  await expect(main).not.toContainText("p@ss");
  await expect(main.getByText(/^idle · 30 fps max$/)).toBeVisible();
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

test("a guide action opens the settings section it names, and no dash or arrow glyph is left in the copy", async ({ page }) => {
  for (const [action, section] of [["Open settings", "Appearance"], ["Manage access", "API and MCP"], ["Browse plugins", "Plugins"]]) {
    await dashboard(page, { dialog: "guide" });
    expect(await page.getByRole("dialog").innerText()).not.toMatch(/[—→←↗]/);
    await expect(page.getByRole("link", { name: "Documentation opens in a new tab" })).toBeVisible();
    await page.getByRole("button", { name: action }).click();
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: section, exact: true })).toHaveAttribute("aria-current", "page");
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

  await page.evaluate(() => {
    (window as any).__pg.setState({ dialog: null });
    location.hash = "#/prints";
  });
  await expect(page.getByRole("button", { name: "browse" })).toBeVisible();
  await expect(page.locator("input[type=file]")).toBeHidden();
});

test("the glass sliders read out percentages, and two review frames from one minute are told apart", async ({ page }) => {
  const settings = { ...engine().settings, glass: { opacity: 0.5, tone: 0.25 } };
  await dashboard(page, { engine: engine({ settings, reviews: [review({ frames: 2 })] }) }, "/monitors/m1/review/r1");
  await expect(page.getByRole("slider", { name: "Opacity", includeHidden: true }).first()).toHaveAttribute("aria-valuetext", "50%");
  await expect(page.getByRole("slider", { name: "Tone", includeHidden: true }).first()).toHaveAttribute("aria-valuetext", "25%");

  await emit(page, {
    event: "review", ...review({ frames: 2 }),
    frames: [{ id: "s1", ts: 60, score: 0.1, kind: "spaced", size: 1 }, { id: "s2", ts: 70, score: 0.1, kind: "spaced", size: 1 }],
  });
  const sheet = page.locator("main");
  await sheet.getByRole("radio", { name: "Yes" }).check();
  await expect(sheet.getByRole("button", { name: /^Frame 1 of 2 at .*, marked Good/ })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^Frame 2 of 2 at .*, marked Good/ })).toBeVisible();
  await expect(sheet.getByRole("button", { name: /^Don't send frame 2 of 2 at / })).toBeVisible();
});

test("a slider is named by its label and reads its formatted value", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1");
  await page.getByRole("tab", { name: "Tune" }).click();
  const threshold = page.getByRole("slider", { name: "Alert threshold", exact: true });

  await expect(threshold).toHaveAttribute("aria-valuetext", "0.60");
  await page.evaluate(() => (location.hash = "#/monitors/m1/edit"));
  await expect(page.getByRole("switch", { name: "Watch this monitor", exact: true })).toBeVisible();
});

test("an alerting monitor shows no signal below its banner and no inference figures, and its row is selected from its frame", async ({ page }) => {
  await dashboard(page, {
    engine: engine({
      cameras: [camera({ online: false }), camera({ id: "c2", name: "Garage" })],
      monitors: [monitor({ alert: { score: 0.9, action: "pause", ts: 1 } }), monitor({ id: "m2", name: "Ender", camera_id: "c2" })],
    }),
    history: { m1: [{ ts: 1, score: 0.9 }] },
  });
  const hero = page.getByRole("region", { name: "Prusa, selected monitor" });
  await expect(hero).not.toContainText("5.0/5.0");
  await expect(hero.getByRole("img", { name: "risk unknown" })).toBeVisible();

  const banner = (await hero.getByText("DEFECT DETECTED").boundingBox())!;
  const signal = (await hero.getByText("no signal").boundingBox())!;
  expect(signal.y).toBeGreaterThanOrEqual(banner.y + banner.height);

  const enderFrame = page.locator("main li").filter({ hasText: "Ender" }).locator("[data-camera]");
  await enderFrame.scrollIntoViewIfNeeded();
  const frame = (await enderFrame.boundingBox())!;
  await page.mouse.click(frame.x + frame.width / 2, frame.y + frame.height / 2);
  await expect(page.getByRole("region", { name: "Ender, selected monitor" })).toBeVisible();
});

test("an offline camera shows no frame rate in the camera list and no risk in the history", async ({ page }) => {
  const offline = engine({ cameras: [camera({ online: false })] });
  await dashboard(page, { engine: offline, history: { m1: [{ ts: 1, score: 0.9 }] } }, "/cameras");
  const card = page.getByRole("link", { name: /^Workshop/ });
  await expect(card).not.toContainText("5.0");
  await expect(card).toContainText("offline");

  await page.evaluate(() => (location.hash = "#/monitors/m1/history"));
  await expect(page.locator("main").getByRole("img", { name: "risk unknown" })).toBeVisible();
});

test("the saved chip shows only on the form that saved", async ({ page }) => {
  await dashboard(page, {}, "/monitors/m1/edit");
  const panel = page.locator("main");
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
  await dashboard(page, {}, "/settings/updates");
  const acknowledge = async () => {
    await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
    await emit(page, { event: "state", ...engine(), req_id: (await lastSent(page, "settings.update")).req_id });
  };
  const sections = page.getByRole("navigation", { name: "Settings sections" });
  await page.evaluate(() => (window as any).__pg.getState().updateSettings({ theme: "light" }));
  await acknowledge();
  await expect(page.getByText(/saved ✓/)).toBeHidden();
  await sections.getByRole("link", { name: "Storage" }).click();
  await expect(page.getByText(/saved ✓/)).toBeHidden();

  await page.getByRole("switch", { name: "Ask me to review frames after a print" }).click();
  await acknowledge();
  await expect(page.getByText(/saved ✓/)).toBeVisible();
  await sections.getByRole("link", { name: "Updates" }).click();
  await expect(page.getByText(/saved ✓/)).toBeHidden();
});

test("the updates section opens the release notes whether or not an update is waiting", async ({ page }) => {
  await dashboard(page, {}, "/settings/updates");
  await page.getByRole("button", { name: "Release notes" }).click();
  expect(await page.evaluate(() => (window as any).__pg.getState().dialog)).toBe("update");
});

test("a token revoke greys out only its own button, and a token name stays until the hub accepts it", async ({ page }) => {
  const tokens = [
    { id: "t1", name: "ci", scope: "read", hint: "pg_aaaa" },
    { id: "t2", name: "ha", scope: "control", hint: "pg_bbbb" },
  ];
  await dashboard(page, { engine: engine({ tokens }) }, "/settings/api");
  await page.getByRole("button", { name: "Revoke" }).first().click();
  await pastDoublePress(page);
  await page.getByRole("button", { name: "Confirm" }).click();
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
  await dashboard(page, { engine: engine({ monitors: [monitor({ alert: { score: 0.9, action: "none", ts: 1 } })] }) }, "/monitors/m1");
  await emit(page, { event: "alert", monitor_id: "m1", score: 0.9, action: "none", ts: 1 });
  await emit(page, { event: "alert", monitor_id: "m1", score: 0.9, action: "pause", ts: 2 });
  const toasts = page.getByRole("alert");

  await expect(toasts.first()).toHaveText("Defect on Prusa, 90%");
  await expect(toasts.last()).toHaveText("Defect on Prusa, 90%, print paused");
  await expect(page.getByRole("region", { name: "Prusa, selected monitor" }).getByText("defect at 90%", { exact: true })).toBeVisible();
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
  await dashboard(page, { engine: engine({ printers: [printer], integrations }) }, "/printers/p1");
  await page.getByRole("button", { name: "Test connection" }).click();
  await emit(page, { event: "printer_test", ok: true, status: "idle", req_id: (await sent(page, "printer.test")).req_id });
  await expect(page.getByText("ok, idle")).toBeVisible();

  await page.getByRole("textbox", { name: "Name" }).fill("MK4 ");
  await expect(page.getByRole("button", { name: "Save printer" })).toBeDisabled();
  await expect(page.getByText("ok, idle")).toBeVisible();
  await page.getByRole("textbox", { name: "Address" }).fill("http://mk3");
  await expect(page.getByText("ok, idle")).toBeHidden();
  await expect(page.getByRole("textbox", { name: "Address" })).toHaveAttribute("autocapitalize", "none");
});

test("a connection or alert test that was never sent leaves its button free", async ({ page }) => {
  const schema = { properties: { url: { title: "Address" } } };
  const printer = { id: "p1", name: "MK4", provider: "octoprint", config: { url: "http://mk4" }, online: true, device_state: null };
  const integrations = [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema }];
  await dashboard(page, { engine: engine({ printers: [printer], integrations }) }, "/printers/p1");
  await page.evaluate(() => (window as any).__pg.setState({ link: { send: () => false, close() {} } }));
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
  await dashboard(page, {}, "/cameras/new");
  await page.evaluate(() => (window as any).__pg.setState({ link: { send: () => false, close() {} } }));
  await page.getByRole("radio", { name: "This machine" }).check();

  await expect(page.getByRole("radio", { name: "This machine" })).toBeChecked();
  await expect(page.getByText("scanning devices")).toBeHidden();
  await expect(page.getByText("no unregistered cameras found")).toBeHidden();
});

test("removing a camera the hub never hears about leaves it publishing and remembered for the next load", async ({ page }) => {
  const publishing = camera({ id: "c2", name: "Bench", source: { kind: "path", path: "dev-bench-1" } });
  await dashboard(page, { engine: engine({ cameras: [publishing] }) }, "/cameras/c2");
  await page.evaluate(async () => {
    const win = window as any;
    const stream = await import("/src/stream.ts" as string);
    stream.published.set("dev-bench-1", () => (win.__stopped = true));
    localStorage.setItem("pg-publishers", JSON.stringify({ "dev-bench-1": "usb" }));
    win.__pg.setState({ link: { send: () => false, close() {} } });
  });
  await page.getByRole("button", { name: "Remove" }).click();
  await pastDoublePress(page);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("status").filter({ hasText: "wasn't sent" })).toBeVisible();

  expect(await page.evaluate(() => (window as any).__stopped)).toBeUndefined();
  expect(await page.evaluate(() => localStorage.getItem("pg-publishers"))).toContain("dev-bench-1");
});

const fakeWebcam = (opens: boolean) => {
  const win = window as any;
  win.__opened = 0;
  const open = async () => {
    win.__opened += 1;
    if (!opens) throw new DOMException("Requested device not found", "NotFoundError");
    return { getTracks: () => [{ stop() {} }], getVideoTracks: () => [{ addEventListener() {} }] };
  };
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: open }, configurable: true });
  win.MediaRecorder = class {
    static isTypeSupported = () => true;
    state = "inactive";
    start() {}
    stop() {}
  };
};

test("a camera published from one tab is left alone by a second tab on the same device until the first lets go", async ({ page, context }) => {
  const second = await context.newPage();
  for (const tab of [page, second]) {
    await tab.addInitScript(fakeWebcam, true);
    await tab.routeWebSocket(/\/api\/publish\//, () => {});
    await dashboard(tab);
  }
  await page.evaluate(async () => {
    const { publishStream } = await import("/src/stream.ts" as string);
    await publishStream("dev-bench-1", "usb");
  });
  const resume = () =>
    second.evaluate(async () => {
      const win = window as any;
      const { resumePublishers, published } = await import("/src/stream.ts" as string);
      win.__down = [];
      await resumePublishers([{ source: { kind: "path", path: "dev-bench-1" } }], (reason: string) => win.__down.push(reason));
      return { opened: win.__opened, publishing: published.has("dev-bench-1"), down: win.__down };
    });
  expect(await resume()).toEqual({ opened: 0, publishing: false, down: [] });

  await page.evaluate(async () => (await import("/src/stream.ts" as string)).published.get("dev-bench-1")());
  await expect.poll(resume).toEqual({ opened: 1, publishing: true, down: [] });
});

test("a published camera that cannot be opened again after a reload says so", async ({ page }) => {
  await page.addInitScript(fakeWebcam, false);
  await page.addInitScript(() => localStorage.setItem("pg-publishers", JSON.stringify({ "dev-bench-1": "usb" })));
  await hub(page, () => {}, engine({ cameras: [camera(), camera({ id: "c2", name: "Bench", source: { kind: "path", path: "dev-bench-1" } })] }));

  await expect(page.getByText("publishing stopped: Requested device not found")).toBeVisible();
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

test("a preset temperature can be cleared and retyped, and a paused print offers resume rather than pause", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "paused", progress: 40, job: "benchy", remaining_s: 60, nozzle: heater, bed: heater },
  };
  const settings = { ...engine().settings, preheat: [{ name: "PLA", nozzle: 200, bed: 60 }] };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })], settings }) }, "/monitors/m1");
  const panel = page.getByRole("region", { name: "Prusa, selected monitor" });
  await expect(panel.getByRole("button", { name: "pause print" })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "resume print" })).toBeEnabled();

  await panel.getByRole("tab", { name: "Preheat" }).click();
  await panel.getByRole("button", { name: "Edit", exact: true }).click();
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

test("pause or resume and cancel are each enabled only when the printer's state allows them", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = (status: string) => ({
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status, progress: 40, job: "benchy", remaining_s: 60, nozzle: heater, bed: heater },
  });
  const expected: Record<string, [string, boolean, boolean]> = {
    idle: ["pause print", false, false],
    offline: ["pause print", false, false],
    printing: ["pause print", true, true],
    paused: ["resume print", true, true],
  };
  for (const [status, [primary, enabled, cancel]] of Object.entries(expected)) {
    await dashboard(page, { engine: engine({ printers: [printer(status)], monitors: [monitor({ printer_id: "p1" })] }) }, "/monitors/m1");
    const panel = page.getByRole("region", { name: "Prusa, selected monitor" });
    await expect(panel.getByRole("button", { name: primary, exact: true })).toBeEnabled({ enabled });
    await expect(panel.getByRole("button", { name: "cancel print", exact: true })).toBeEnabled({ enabled: cancel });
  }
});

test("a heater target typed or stored above the limit is never sent as it is", async ({ page }) => {
  const heater = { actual: 21, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  const settings = { ...engine().settings, preheat: [{ name: "PLA", nozzle: 400, bed: 200 }] };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })], settings }) }, "/monitors/m1");
  const panel = page.getByRole("region", { name: "Prusa, selected monitor" });
  await panel.getByRole("tab", { name: "Preheat" }).click();
  await panel.getByRole("button", { name: /^PLA/ }).click();
  expect(await sent(page, "printer.heat")).toMatchObject({ nozzle: 350, bed: 150 });

  await panel.getByRole("button", { name: "Edit", exact: true }).click();
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

test("a print the reviewer chose not to send reads as reviewed and can still be opened", async ({ page }) => {
  const reviews = [review({ status: "dismissed" }), review({ id: "r2", status: "skipped" })];
  await dashboard(page, { engine: engine({ reviews }) }, "/monitors/m1/history");
  const prints = page.locator("main").getByRole("listitem");
  await expect(prints.filter({ hasText: /frames · not reviewed/ })).toHaveCount(1);
  const skipped = prints.filter({ hasText: "reviewed, not sent" });
  await expect(skipped).toHaveCount(1);
  await skipped.getByRole("link", { name: "Review" }).click();
  await expect(page).toHaveURL(/#\/monitors\/m1\/review\/r2$/);
});

test("a print that kept no frames is not offered for review, and a snapshot is opened and closed on its own", async ({ page }) => {
  const reviews = [review({ status: "dismissed", frames: 0 }), review({ id: "r2", frames: 4 })];
  await dashboard(page, { engine: engine({ reviews }) }, "/monitors/m1/history");
  const sheet = page.locator("main");
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

test("a monitor's feed behind a dialog says it is paused", async ({ page }) => {
  await dashboard(page, { dialog: "guide" });
  await expect(page.getByRole("region", { name: "Prusa, selected monitor", includeHidden: true }).getByText("feed paused")).toBeAttached();
});

test("a camera with no Remove says why in the text", async ({ page }) => {
  const owned = camera({ id: "c2", name: "Printer cam", printer_id: "p1" });
  const declared = camera({ id: "c3", name: "Passed in", declared: true });
  const printers = [{ id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true, device_state: null }];
  await dashboard(page, { engine: engine({ cameras: [owned, declared], printers }) }, "/cameras/c3");

  await expect(page.getByText("Passed in by the deployment, remove its devices entry to remove this camera.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
  await page.getByRole("tab", { name: /^Printer cams/ }).click();
  await page.getByRole("link", { name: /^Printer cam/ }).click();
  await expect(page.getByText("Managed by its printer integration, remove the printer to remove this camera.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
});

test("camera and settings controls are named, and choices say which is selected", async ({ page }) => {
  await dashboard(page, {}, "/cameras/c1");
  await expect(page.locator("main")).toContainText("online");
  await expect(page.getByRole("radiogroup", { name: "Rotation" }).or(page.getByRole("group", { name: "Rotation" }))).toBeVisible();
  await expect(page.getByRole("radio", { name: "0°", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "90°" })).not.toBeChecked();

  await page.evaluate(() => (location.hash = "#/cameras/new"));
  await expect(page.getByRole("textbox", { name: "Stream URL" })).toHaveAttribute("autocapitalize", "none");

  await page.evaluate(() => (location.hash = "#/settings/api"));
  await expect(page.getByRole("combobox", { name: "Token scope" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Token name" })).toBeVisible();
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Alerts" }).click();
  await expect(page.getByText("for monitors with push notifications on")).toBeVisible();
});

test("a dialog opened with the pointer shows no focus ring until the keyboard is used", async ({ page }) => {
  await dashboard(page);
  await page.getByRole("button", { name: "Add monitor" }).click();
  const close = page.getByRole("button", { name: "Close dialog" });
  await expect(close).toBeFocused();
  await expect(close).toHaveCSS("outline-style", "none");

  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveCSS("outline-style", "solid");
});

test.describe("on a touch screen", () => {
  test.use({ hasTouch: true, viewport: { width: 393, height: 852 } });

  test("the top bar's buttons and the dock's links each take a tap 44 pixels across", async ({ page }) => {
    await dashboard(page);
    const targets = [
      ...["Open the guide", "Report a bug", "Add monitor"].map((name) => page.getByRole("banner").getByRole("button", { name })),
      ...["Monitors", "Prints", "Cameras", "Printers", "Settings"].map((name) => page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name })),
    ];
    for (const target of targets) {
      const { width, height } = (await target.boundingBox())!;
      expect(Math.min(width, height)).toBeGreaterThanOrEqual(44);
    }
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
  await dashboard(page, { engine: engine({ prints: [printFile()] }) }, "/prints/f1");
  await expect(page.getByRole("slider", { name: "Layers shown" })).toBeVisible();

  await page.evaluate(() => {
    (window as any).__megabytes = 40;
    location.hash = "#/";
  });
  await expect(page.getByRole("slider", { name: "Layers shown" })).toHaveCount(0);
  await page.evaluate(() => (location.hash = "#/prints/f1"));
  await expect(page.getByText("files over 32 MB are not drawn")).toBeVisible();
  expect(await page.evaluate(() => (window as any).__cancelledAt)).toBeLessThan(36);
});

const jobPrinter = (status = "printing") => ({
  id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
  device_state: { status, progress: 40, job: "benchy", remaining_s: 60, nozzle: { actual: 21, target: 0 }, bed: { actual: 21, target: 0 } },
});

const withLayout = (monitors: Record<string, string[]>, over = {}) =>
  engine({ settings: { ...engine().settings, layout: { monitors: { order: [], pinned: [], hidden: [], ...monitors } } }, ...over });

const hubAway = (page: Page, away: boolean) =>
  page.evaluate((away) => {
    const win = window as any;
    win.__link ??= win.__pg.getState().link;
    win.__pg.setState({ link: away ? { send: () => false, close() {} } : win.__link });
  }, away);

const allSent = (page: Page, cmd: string) => page.evaluate((cmd) => (window as any).__sent.filter((c: any) => c.cmd === cmd), cmd);

test("cancelling a print takes a second press that a double click is not, and the button stands down on Escape, a press elsewhere or a few seconds", async ({ page }) => {
  await page.clock.install();
  await dashboard(page, { engine: engine({ printers: [jobPrinter()], monitors: [monitor({ printer_id: "p1" })] }) }, "/monitors/m1");
  const panel = page.locator("main");
  const cancel = panel.getByRole("button", { name: "cancel print", exact: true });
  const confirm = panel.getByRole("button", { name: "Confirm", exact: true });
  const { width, height } = (await cancel.boundingBox())!;

  await cancel.click();
  await expect(confirm).toBeFocused();
  await expect(panel.getByRole("status").filter({ hasText: "Press again to confirm" })).toHaveCount(1);
  expect(await confirm.boundingBox()).toMatchObject({ width, height });
  expect(await sent(page, "printer.action")).toBeUndefined();

  await page.keyboard.press("Escape");
  await expect(cancel).toBeVisible();
  await expect(panel).toBeVisible();

  await cancel.click();
  await panel.getByRole("heading", { name: "Prusa", level: 2 }).click();
  await expect(confirm).toBeHidden();

  await cancel.click();
  await page.keyboard.press("Tab");
  await expect(confirm).toBeHidden();

  await cancel.click();
  await expect(confirm).toBeVisible();
  await page.clock.fastForward(4500);
  await expect(confirm).toBeHidden();
  expect(await sent(page, "printer.action")).toBeUndefined();

  await cancel.dblclick();
  await expect(confirm).toBeVisible();
  expect(await sent(page, "printer.action")).toBeUndefined();
  await pastDoublePress(page);
  await confirm.click();
  expect(await sent(page, "printer.action")).toMatchObject({ id: "p1", action: "cancel" });
});

test("resetting the layout and removing a printer or a plugin each take a confirming press", async ({ page }) => {
  const plugin = demoPlugin({ enabled: false });
  await dashboard(page, { engine: { ...withPlugins([plugin]), ...withLayout({ pinned: ["m1"] }, { printers: [jobPrinter()], plugins: [plugin] }) }, customising: true });
  const confirm = page.getByRole("button", { name: "Confirm", exact: true });
  const pinned = () => page.evaluate(() => (window as any).__pg.getState().engine.settings.layout.monitors?.pinned);

  await page.getByRole("button", { name: "Reset layout" }).click();
  expect(await pinned()).toEqual(["m1"]);
  await pastDoublePress(page);
  await confirm.click();
  expect(await pinned()).toBeUndefined();

  await routeTo(page, "/printers/p1");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  expect(await sent(page, "printer.remove")).toBeUndefined();
  await pastDoublePress(page);
  await confirm.click();
  expect(await sent(page, "printer.remove")).toMatchObject({ id: "p1" });

  await routeTo(page, "/settings/plugins/demo");
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  expect(await sent(page, "plugin.remove")).toBeUndefined();
  await pastDoublePress(page);
  await confirm.click();
  expect(await sent(page, "plugin.remove")).toMatchObject({ id: "demo" });
});

test("Escape closes the upload sheet only when pressed twice", async ({ page }) => {
  await stagePrint(page);
  const sheet = page.getByRole("dialog", { name: "Upload cube.gcode" });
  await expect(sheet).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(sheet.getByRole("status").filter({ hasText: "Close again to discard" })).toBeVisible();
  await pastDoublePress(page);
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
});

const routeTo = (page: Page, route: string) => page.evaluate((route) => (location.hash = route), `#${route}`);

test("a dialog the browser closes by itself stays in step with the dashboard", async ({ page }) => {
  await stagePrint(page);
  const sheet = page.getByRole("dialog", { name: "Upload cube.gcode" });
  const armed = sheet.getByRole("status").filter({ hasText: "Close again to discard" });
  const pageScrollLocked = () => page.evaluate(() => document.body.style.overflow === "hidden");

  await page.keyboard.press("Escape");
  await page.waitForTimeout(4500);
  await page.keyboard.press("Escape");
  await expect(armed).toBeVisible();
  await expect(sheet).toBeVisible();
  expect(await pageScrollLocked()).toBe(true);
  await pastDoublePress(page);
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  expect(await pageScrollLocked()).toBe(false);

  await page.evaluate(() => (window as any).__pg.getState().openDialog("guide"));
  await expect(page.getByRole("dialog", { name: "Guide" })).toBeVisible();
  await page.evaluate(() => document.querySelector("dialog")!.close());
  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().dialog)).toBeNull();
  expect(await pageScrollLocked()).toBe(false);
});

test("switching the review off says what it deletes, and asks twice while a print is waiting", async ({ page }) => {
  await dashboard(page, { engine: engine({ reviews: [review()] }) }, "/settings/storage");
  const toggle = page.getByRole("switch", { name: "Ask me to review frames after a print" });
  await expect(page.getByText("Turning this off deletes the frames kept so far.")).toBeVisible();

  await toggle.click();
  await expect(page.getByRole("status").filter({ hasText: "1 print waiting for review will be dismissed" })).toBeVisible();
  await expect(toggle).toBeChecked();
  await pastDoublePress(page);
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText("keeps only alert frames while this is off")).toBeVisible();
  await expect.poll(() => sent(page, "settings.update")).toMatchObject({ patch: { feedback: "off" } });

  await page.reload();
  await dashboard(page, {}, "/settings/storage");
  await toggle.click();
  await expect(toggle).not.toBeChecked();
});

test("the toolpath leaves room to reach the fields on a phone held sideways, and is exposed as an image", async ({ page }) => {
  await page.setViewportSize({ width: 740, height: 360 });
  await stagePrint(page);
  const box = (await page.getByRole("img", { name: "Toolpath of cube.gcode" }).boundingBox())!;

  expect(box.height).toBeLessThanOrEqual(181);
  expect(box.width / box.height).toBeCloseTo(4 / 3, 1);
});

test("the plugins tab lists what is installed before the catalogue arrives, and asks again for what a dropped hub never answered", async ({ page }) => {
  const zipped = demoPlugin({ enabled: false, granted: [], source: { kind: "file", filename: "demo.zip" } });
  await dashboard(page, { engine: withPlugins([zipped]), reconnecting: true }, "/settings/plugins");
  await expect(page.getByText("Loading the catalogue…")).toBeVisible();
  await page.getByRole("switch", { name: "Enable Demo" }).click();
  await expect(page.getByText("Reading its code…")).toBeVisible();
  expect(await sent(page, "plugin.catalogue")).toBeUndefined();
  expect(await sent(page, "plugin.code")).toBeUndefined();

  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(() => sent(page, "plugin.catalogue")).toBeDefined();
  await expect.poll(() => sent(page, "plugin.code")).toMatchObject({ id: "demo" });

  await page.getByRole("button", { name: "Cancel" }).click();
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: true }));
  await page.getByRole("button", { name: "Demo", exact: true }).click();
  await expect(page.getByText("Reading its page…")).toBeVisible();
  expect(await sent(page, "plugin.page")).toBeUndefined();
  await page.evaluate(() => (window as any).__pg.setState({ reconnecting: false }));
  await expect.poll(() => sent(page, "plugin.page")).toMatchObject({ id: "demo" });
});

test("a dashboard with every monitor hidden says so and opens the layout", async ({ page }) => {
  await dashboard(page, { engine: withLayout({ hidden: ["m1"] }) });
  await expect(page.getByText("1 monitor hidden")).toBeVisible();

  await page.getByRole("main").getByRole("button", { name: "Layout" }).last().click();
  await expect(page.getByRole("button", { name: "Prusa · show" })).toBeVisible();
});

test("hidden plugin panels are counted as panels, not as monitors", async ({ page }) => {
  const plugins = [demoPlugin(), demoPlugin({ id: "other" })];
  await dashboard(page, { engine: { ...withPlugins(plugins), ...withLayout({ hidden: ["m1", "demo", "other"] }, { plugins }) } });
  await expect(page.getByText("1 monitor and 2 plugin panels hidden")).toBeVisible();

  await emit(page, { event: "state", ...withLayout({ hidden: ["demo"] }, { monitors: [], plugins: [plugins[0]] }) });
  await expect(page.getByText("1 plugin panel hidden")).toBeVisible();
});

test("the library filter falls back to every printer when the one it names is removed", async ({ page }) => {
  const prints = [printFile({ printer_ids: ["p1"] }), printFile({ id: "f2", name: "bracket", printer_ids: [] })];
  await dashboard(page, { engine: engine({ printers: [jobPrinter()], prints }) }, "/prints");
  const filter = page.getByRole("combobox", { name: "Filter by printer" });
  await filter.selectOption("p1");
  await expect(page.getByText("1 file", { exact: true })).toBeVisible();

  await emit(page, { event: "state", ...engine({ printers: [{ ...jobPrinter(), id: "p2", name: "Voron" }], prints }) });
  await expect(filter).toHaveValue("");
  await expect(page.getByText("2 files", { exact: true })).toBeVisible();
});

test("focus moves to the next control when the one pressed goes away", async ({ page }) => {
  const heater = { actual: 20, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  const settings = { ...engine().settings, preheat: [{ name: "PLA", nozzle: 200, bed: 60 }, { name: "PETG", nozzle: 240, bed: 80 }] };
  await dashboard(page, { engine: engine({ printers: [printer], monitors: [monitor({ printer_id: "p1" })], settings }), dialog: "intro" });
  const pressed = async (name: string | RegExp) => {
    const control = page.getByRole("button", { name, exact: true });
    await control.focus();
    await page.keyboard.press("Enter");
  };

  const next = page.getByRole("button", { name: "Next", exact: true });
  await next.focus();
  while (await next.isVisible()) await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Close", exact: true })).toBeFocused();

  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/cameras/c1");
  await pressed("Set crop");
  await expect(page.getByRole("button", { name: "Done", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^(Set|Edit) crop$/ })).toBeFocused();

  await page.evaluate(() => (window as any).__pg.getState().openDialog("report"));
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Attach screenshots" }).click();
  await (await chooser).setFiles({ name: "shot.png", mimeType: "image/png", buffer: Buffer.from("png") });
  await pressed("Remove shot.png");
  await expect(page.getByRole("button", { name: "Attach screenshots" })).toBeFocused();

  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/settings/api");
  await expect(page.getByRole("combobox", { name: "Token scope" })).toBeVisible();
  await page.evaluate(() => (window as any).__pg.setState({ createdToken: { name: "ha", secret: "pg_secret" } }));
  await pressed("Dismiss");
  await expect(page.getByRole("combobox", { name: "Token scope" })).toBeFocused();

  await routeTo(page, "/monitors/m1");
  await page.getByRole("tab", { name: "Preheat" }).click();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await pressed("Remove PLA");
  await expect(page.getByRole("button", { name: "Remove PETG" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "+ Add preset" })).toBeFocused();
});

test("an unpinned row dragged onto a pinned one is dropped among the unpinned", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1200 });
  const monitors = [monitor(), monitor({ id: "m2", name: "Voron" }), monitor({ id: "m3", name: "Ender" })];
  await dashboard(page, { engine: withLayout({ order: ["m1", "m2", "m3"], pinned: ["m1"] }, { monitors }), customising: true });
  const from = (await page.getByRole("button", { name: "Drag Ender to reorder" }).boundingBox())!;
  const onto = (await page.getByRole("button", { name: "Drag Prusa to reorder" }).boundingBox())!;

  await page.mouse.move(from.x + 5, from.y + 5);
  await page.mouse.down();
  await page.mouse.move(onto.x + 5, onto.y + 5, { steps: 12 });
  await page.mouse.up();

  await expect.poll(() => page.evaluate(() => (window as any).__pg.getState().engine.settings.layout.monitors.order)).toEqual(["m1", "m3", "m2"]);
  await expect(page.getByRole("main").getByRole("link", { name: /^(Prusa|Voron|Ender)$/ })).toHaveText(["Prusa", "Ender", "Voron"]);
});

test("a file rename the hub refuses goes back to the old name", async ({ page }) => {
  const { commands, sockets } = await hub(page, undefined, library([printFile()]).engine, "/prints/f1");
  const name = page.getByRole("textbox", { name: "Name" });
  await name.fill("Boat");
  await name.blur();
  const renames = () => commands.filter((c) => c.cmd === "print.update");
  await expect.poll(() => renames()[0]).toMatchObject({ id: "f1", patch: { name: "Boat" } });
  await expect(page.getByRole("heading", { name: "Boat" })).toBeVisible();

  sockets[0].send(JSON.stringify({ event: "error", message: "no", req_id: renames()[0].req_id }));
  await expect(name).toHaveValue("Benchy");
});

test("a heater target or a plugin secret typed while the hub is away is not shown as saved", async ({ page }) => {
  const keyed = demoPlugin({ manifest: { ...demoPlugin().manifest, secrets: { api_key: "Your key" } } });
  await dashboard(page, { engine: { ...withPlugins([keyed]), printers: [jobPrinter("idle")], monitors: [monitor({ printer_id: "p1" })] } }, "/monitors/m1");
  await page.getByRole("tab", { name: "Preheat" }).click();
  await hubAway(page, true);
  const target = page.getByRole("spinbutton", { name: "nozzle target" });
  await target.fill("250");
  await target.blur();
  await expect(target).toHaveValue("0");
  await expect(target).toBeEnabled();

  await routeTo(page, "/settings/plugins/demo");
  const secret = page.getByPlaceholder("Not set");
  await secret.fill("s3cret");
  await secret.blur();
  await expect(secret).toHaveValue("s3cret");

  await hubAway(page, false);
  await secret.focus();
  await secret.blur();
  await expect(secret).toHaveValue("");
  expect(await sent(page, "plugin.secrets")).toMatchObject({ secrets: { api_key: "s3cret" } });
});

test("the install box sends once, keeps what was typed when it could not be sent, and Update shows it is working", async ({ page }) => {
  await dashboard(page, { engine: withPlugins([demoPlugin()]) }, "/settings/plugins");
  const box = page.getByRole("textbox", { name: "GitHub repository" });

  await hubAway(page, true);
  await box.fill("someone/thing");
  await box.press("Enter");
  await expect(box).toHaveValue("someone/thing");

  await hubAway(page, false);
  await box.press("Enter");
  await expect(box).toHaveValue("");
  await box.fill("someone/other");
  await box.press("Enter");
  expect(await allSent(page, "plugin.install")).toHaveLength(1);

  await emit(page, { event: "state", ...withPlugins([demoPlugin()]), req_id: (await sent(page, "plugin.install")).req_id });
  await page.getByRole("button", { name: "Demo", exact: true }).click();
  await page.getByRole("button", { name: "Update", exact: true }).click();
  await expect(page.getByRole("button", { name: "Updating…" })).toBeDisabled();
  expect(await allSent(page, "plugin.install")).toHaveLength(2);
});

test("a review says its frames are loading, and cannot be sent while the review is switched off", async ({ page }) => {
  const dismissed = review({ status: "dismissed" });
  await dashboard(page, { engine: engine({ reviews: [dismissed], settings: { ...engine().settings, feedback: "off" } }) }, "/monitors/m1/review/r1");
  const sheet = page.getByRole("main");
  const loading = sheet.getByRole("status").filter({ hasText: "loading the frames" });
  await sheet.getByRole("radio", { name: "No, something went wrong" }).check();
  await expect(loading).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Send 3 frames" })).toBeDisabled();
  await expect(sheet.getByText("Alert frames are marked as real failures. Press a frame to change its label, or use the × to leave it out.")).toBeVisible();

  const frames = [
    { id: "a1", ts: 60, score: 0.9, kind: "alert", action: "pause", size: 1 },
    { id: "s1", ts: 120, score: 0.1, kind: "spaced", size: 1 },
    { id: "s2", ts: 180, score: 0.1, kind: "spaced", size: 1 },
  ];
  await emit(page, { event: "review", ...dismissed, frames });
  await expect(loading).toHaveCount(0);
  await expect(sheet.getByText("switched off in Settings, so nothing can be sent")).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Send 3 frames" })).toBeDisabled();

  await sheet.getByRole("button", { name: /^Enlarge/ }).first().click();
  await expect(page.getByText("loading picture")).toBeVisible();
});

test("Enter adds a monitor, generates a token and registers a printer, and a printer missing a required field cannot be registered", async ({ page }) => {
  await dashboard(page, { engine: engine({ integrations: keyedIntegrations }), dialog: "monitor" });
  await page.getByRole("combobox", { name: "Camera" }).selectOption("c1");
  await page.getByRole("textbox", { name: "Monitor name" }).fill("Bench");
  await page.keyboard.press("Enter");
  expect(await sent(page, "monitor.add")).toMatchObject({ monitor: { name: "Bench", camera_id: "c1" } });

  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/settings/api");
  await page.getByRole("textbox", { name: "Token name" }).fill("ci");
  await page.keyboard.press("Enter");
  expect(await sent(page, "token.create")).toMatchObject({ name: "ci", scope: "read" });

  await routeTo(page, "/printers/new");
  await page.getByRole("combobox", { name: "Printer service" }).selectOption("octoprint");
  const register = page.getByRole("button", { name: "Register printer" });
  await expect(register).toBeDisabled();
  await page.getByLabel("API key").fill("abc");
  await expect(page.getByLabel("API key")).toHaveAttribute("autocomplete", "new-password");
  await page.getByLabel("Address").fill("http://mk4");
  await expect(register).toBeEnabled();
  await page.keyboard.press("Enter");
  expect(await sent(page, "printer.add")).toMatchObject({ printer: { provider: "octoprint", config: { url: "http://mk4", api_key: "abc" } } });
});

test("the broker port only takes a whole port number", async ({ page }) => {
  await dashboard(page, {}, "/settings/home-assistant");
  await page.getByRole("switch", { name: "Publish to an MQTT broker" }).click();
  const port = page.getByRole("spinbutton", { name: "Broker port" });

  await expect(port).toHaveAttribute("min", "1");
  await expect(port).toHaveAttribute("max", "65535");
  await expect(port).toHaveAttribute("step", "1");
});

test("a printer's status, the chosen theme and links that leave the dashboard are named", async ({ page }) => {
  const update = { current: "1.0.0", latest: "2.0.0", available: true, download: "https://example.com/app.dmg", checked_at: 0, releases_url: "https://example.com" };
  await dashboard(page, { engine: engine({ printers: [jobPrinter()], update }) }, "/printers/p1");
  await expect(page.getByRole("main").getByText("online")).toBeVisible();

  const newTab = (link: string | RegExp) => page.getByRole("link", { name: link }).getByRole("img", { name: "opens in a new tab" });
  await page.evaluate(() => (window as any).__pg.getState().openDialog("update"));
  await expect(newTab(/Download v2\.0\.0/)).toBeVisible();
  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/settings/storage");
  await expect(newTab(/What's sent/)).toBeVisible();

  await page.getByRole("link", { name: "Appearance" }).click();
  await page.getByRole("button", { name: "+ New" }).click();
  await page.getByRole("textbox", { name: "Theme name" }).fill("Workshop");
  await page.getByRole("button", { name: "Save theme" }).click();
  await expect(page.getByRole("button", { name: "Workshop dark" })).toHaveAttribute("aria-pressed", "true");
});

test("a wildcard over the end of an address is listed with what reaches your own network", async ({ page }) => {
  const manifest = { ...demoPlugin().manifest, permissions: ["net", "net:local"], urls: ["http://*.168.1.1/*", "http://*.0x1/*", "https://*.example.com/*"] };
  const plugin_permissions = [
    { id: "net", label: "Reach the internet", description: "", urls: true },
    { id: "net:local", label: "Reach your own network", description: "", urls: true },
  ];
  await dashboard(page, { engine: { ...withPlugins([demoPlugin({ enabled: false, manifest })]), plugin_permissions } }, "/settings/plugins/demo");

  await expect(page.getByRole("row", { name: /Reach your own network/ }).getByRole("listitem")).toHaveCount(2);
  await expect(page.getByRole("row", { name: /Reach the internet/ }).getByRole("listitem")).toHaveText([/example\.com/]);
});

test("the redirect address to register swaps in 127.0.0.1 only for a hub opened at localhost itself", async ({ page, baseURL }) => {
  const oauth = { label: "Thing", authorize_url: "https://thing.example/a", token_url: "https://thing.example/t", register_url: "", scopes: [] };
  const plugin = demoPlugin({ manifest: { ...demoPlugin().manifest, permissions: ["oauth"], oauth }, granted: ["oauth"] });
  const state = { ...withPlugins([plugin]), plugin_permissions: [{ id: "oauth", label: "Sign in", description: "" }], plugin_oauth_callback: "/oauth/callback" };
  const port = new URL(baseURL!).port;
  for (const [host, shown] of [["localhost", "127.0.0.1"], ["localhost.localhost", "localhost.localhost"]]) {
    await page.goto(`http://${host}:${port}/#/settings/plugins/demo`);
    await page.waitForFunction(() => Boolean((window as any).__pg?.getState().link));
    await page.evaluate((engine) => (window as any).__pg.setState({ phase: "ready", link: { send() {}, close() {} }, engine }), state);
    await expect(page.getByText(`http://${shown}:${port}/oauth/callback`, { exact: true })).toBeVisible();
  }
});

test("a plugin whose sign-in address cannot be read still opens, showing the address as written", async ({ page }) => {
  const oauth = { label: "Thing", authorize_url: "https://256.256.256.256/a", token_url: "https://256.256.256.256/t", register_url: "", scopes: [] };
  const state = withPlugins([demoPlugin({ enabled: false, manifest: { ...demoPlugin().manifest, permissions: ["oauth"], oauth } })]);
  await dashboard(page, { engine: { ...state, plugin_permissions: [{ id: "oauth", label: "Sign in", description: "" }] } }, "/settings/plugins/demo");

  await expect(page.getByText("Sign in at https://256.256.256.256/a")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove", exact: true })).toBeVisible();
});

test("a toast raised over a dialog on a phone sits at the top, clear of the dialog's buttons", async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 852 });
  await dashboard(page, { dialog: "report" });
  await page.evaluate(() => (window as any).__pg.getState().toast("info", "Diagnostics saved"));
  const box = (await page.getByRole("dialog").getByRole("status").filter({ hasText: "Diagnostics saved" }).boundingBox())!;
  const save = (await page.getByRole("button", { name: "Send report" }).boundingBox())!;

  expect(box.y + box.height).toBeLessThan(852 / 4);
  expect(box.y + box.height).toBeLessThan(save.y);
});

test("settings copy says things plainly", async ({ page }) => {
  await dashboard(page, { engine: engine({ monitors: [] }) }, "/settings/alerts");
  await expect(page.getByText("Channels hold credentials, so they apply when you press Save.")).toBeVisible();
  await page.getByRole("link", { name: "Home Assistant" }).click();
  await expect(page.getByText("Broker settings open a live connection, so they apply when you press Save.")).toBeVisible();
  await page.getByRole("link", { name: "API and MCP" }).click();
  await expect(page.getByText("Control includes read, and manage includes both.")).toBeVisible();

  await page.evaluate(() => (window as any).__pg.getState().openDialog("report"));
  await expect(page.getByText("Describe what went wrong and it goes straight to me")).toBeVisible();
  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/");
  await expect(page.getByRole("button", { name: "How PrintGuard works", exact: true })).toBeVisible();
});

test("buttons, tabs, the close button and the small controls are 44 pixels to a finger", async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  const shortSide = async (target: ReturnType<Page["locator"]>) => {
    const box = (await target.boundingBox())!;
    return Math.min(box.width, box.height);
  };
  const fitsAFinger = (target: ReturnType<Page["locator"]>) => expect.poll(() => shortSide(target)).toBeGreaterThanOrEqual(44);
  const takesAFinger = async (target: ReturnType<Page["locator"]>) => {
    await expect
      .poll(() =>
        target.evaluate((control) => {
          control.scrollIntoView({ block: "center" });
          const box = control.getBoundingClientRect();
          const centre = [box.x + box.width / 2, box.y + box.height / 2];
          return [[-21, 0], [21, 0], [0, -21], [0, 21]].every(([x, y]) => control.contains(document.elementFromPoint(centre[0] + x, centre[1] + y)));
        }),
      )
      .toBe(true);
  };
  const heater = { actual: 20, target: 0 };
  const printer = {
    id: "p1", name: "MK4", provider: "octoprint", config: {}, online: true,
    device_state: { status: "idle", progress: 0, job: null, remaining_s: null, nozzle: heater, bed: heater },
  };
  const state = engine({
    reviews: [review({ frames: 1 })],
    printers: [printer],
    monitors: [monitor({ printer_id: "p1" })],
    tokens: [{ id: "t1", name: "ha", scope: "read", hint: "pg_1" }],
    settings: { ...engine().settings, preheat: [{ name: "PLA", nozzle: 200, bed: 60 }] },
  });
  await dashboard(page, { engine: state }, "/settings/appearance");

  await fitsAFinger(page.getByRole("link", { name: "Back" }));
  await fitsAFinger(page.getByRole("button", { name: "+ New" }));
  await page.getByRole("button", { name: "+ New" }).click();
  await fitsAFinger(page.getByLabel(/ colour$/).first());

  await routeTo(page, "/settings/api");
  await expect(page.getByRole("combobox", { name: "Token scope" })).toBeVisible();
  await page.evaluate(() => (window as any).__pg.setState({ createdToken: { name: "ha", secret: "pg_secret" } }));
  await takesAFinger(page.getByRole("button", { name: "Dismiss" }));

  await page.evaluate(() => (window as any).__pg.getState().openDialog("report"));
  await fitsAFinger(page.getByText("What's sent with your report"));
  await fitsAFinger(page.getByRole("button", { name: "Close dialog" }));

  await page.evaluate(() => (window as any).__pg.getState().openDialog(null));
  await routeTo(page, "/prints");
  await takesAFinger(page.getByRole("button", { name: "browse" }));

  await routeTo(page, "/monitors/m1");
  await fitsAFinger(page.getByRole("tab", { name: "Preheat" }));
  await page.getByRole("tab", { name: "Preheat" }).click();
  await takesAFinger(page.getByRole("button", { name: "Heaters off" }));
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await fitsAFinger(page.getByRole("button", { name: "Remove PLA" }));

  await page.evaluate(() => (window as any).__pg.setState({ customising: true }));
  await fitsAFinger(page.getByRole("button", { name: "Drag Prusa to reorder" }));
  await fitsAFinger(page.getByRole("button", { name: "Move Prusa down" }));

  await page.evaluate(() => (window as any).__pg.setState({ customising: false, snapshotCache: { s1: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E" } }));
  await routeTo(page, "/monitors/m1/review/r1");
  await emit(page, { event: "review", ...review({ frames: 1 }), frames: [{ id: "s1", ts: 60, score: 0.1, kind: "spaced", size: 1 }] });
  await fitsAFinger(page.getByRole("radio", { name: "Yes" }).locator(".."));
  await page.getByRole("radio", { name: "Yes" }).check();
  await fitsAFinger(page.getByRole("button", { name: /^Enlarge frame 1 of 1 at/ }).filter({ visible: true }));
  await fitsAFinger(page.getByRole("button", { name: /^Don't send frame 1 of 1 at/ }).filter({ visible: true }));
  await page.getByRole("tab", { name: "Recording" }).click();
  await fitsAFinger(page.getByText("What's sent", { exact: true }).filter({ visible: true }));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await context.close();
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
  await dashboard(page, { engine: engine({ printers: [keyedPrinter()], integrations: keyedIntegrations }) }, "/printers/p1");
  return page.getByRole("main");
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
  await form.getByRole("button", { name: "Save printer" }).click();
  const saved = await sent(page, "printer.update");
  expect(saved.patch).toEqual({ name: "MK4S", config: { url: "http://mk4" } });
});

test("a key typed over a saved one is sent, then forgotten by the form once the hub has it", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  const key = form.getByLabel(/^API key/);
  await key.fill("fresh");
  await expect(form.getByRole("button", { name: "Remove the stored API key" })).toBeHidden();
  await form.getByRole("button", { name: "Save printer" }).click();
  const saved = await sent(page, "printer.update");
  expect(saved.patch.config).toEqual({ url: "http://mk4", api_key: "fresh" });

  await emit(page, { event: "state", ...engine({ printers: [keyedPrinter()], integrations: keyedIntegrations }), req_id: saved.req_id });
  await expect(key).toHaveValue("");
  await expect(key).toHaveAttribute("placeholder", KEPT_HINT);
  await expect(form.getByRole("button", { name: "Save printer" })).toBeDisabled();

  await key.fill("typo");
  await key.fill("");
  await expect(form.getByRole("button", { name: "Save printer" })).toBeDisabled();
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

  await form.getByRole("button", { name: "Save printer" }).click();
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
  await form.getByRole("button", { name: "Save printer" }).click();
  const refusal = "the printer did not answer";
  await emit(page, { event: "error", message: refusal, req_id: (await sent(page, "printer.update")).req_id });
  await expect(form.getByRole("alert")).toHaveText(refusal);
  await expect(form.getByRole("textbox", { name: "Address" })).toHaveValue("http://mk3");

  await form.getByRole("button", { name: "Save printer" }).click();
  await expect(form.getByRole("alert")).toBeHidden();
  expect((await lastSent(page, "printer.update")).patch.config).toEqual({ url: "http://mk3", api_key: "again" });
});

test("a moved printer address asks for the saved key again and the whole address, and sends neither half-typed", async ({ page }) => {
  const form = await editKeyedPrinter(page);
  const save = form.getByRole("button", { name: "Save printer" });
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
  await dashboard(
    page,
    { engine: engine({ printers: [keyedPrinter({ config: { url: "http://mk4/?apikey=[redacted]" }, secrets_set: [] })], integrations: keyedIntegrations }) },
    "/printers/p1",
  );
  const form = page.getByRole("main");
  const address = form.getByRole("textbox", { name: "Address" });
  const save = form.getByRole("button", { name: "Save printer" });
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
  await dashboard(page, { engine: withSavedChannel() }, "/settings/alerts");
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
  await dashboard(page, { engine: withSavedChannel() }, "/settings/alerts");
  const priority = page.getByRole("textbox", { name: "Priority" });
  await priority.fill("low");
  await page.getByRole("switch", { name: "ntfy" }).click();
  await expect(priority).toBeHidden();
  await page.getByRole("switch", { name: "ntfy" }).click();

  await expect(priority).toHaveValue("low");
  await expect(page.getByLabel(/^Topic address/)).toHaveAccessibleDescription(KEPT_HINT);
});

test("a channel's test result goes when its form is edited", async ({ page }) => {
  await dashboard(page, { engine: withSavedChannel() }, "/settings/alerts");
  await page.getByRole("button", { name: "Send test alert" }).click();
  await emit(page, { event: "notify_test", provider: "ntfy", ok: true, req_id: (await sent(page, "notify.test")).req_id });
  await expect(page.getByText("sent", { exact: true })).toBeVisible();

  await page.getByRole("textbox", { name: "Priority" }).fill("low");
  await expect(page.getByText("sent", { exact: true })).toBeHidden();
});

test("the broker form refuses an empty host and asks for the password again when the address moves", async ({ page }) => {
  const broker = { enabled: true, host: "broker.lan", username: "pg" };
  const state = engine({ settings: { ...engine().settings, mqtt: broker }, secrets_set: { notifiers: {}, mqtt: ["password"] } });
  await dashboard(page, { engine: state }, "/settings/home-assistant");
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
  await dashboard(page, { engine: state }, "/settings/home-assistant");
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
  await dashboard(page, { engine: state }, "/settings/home-assistant");
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
  await dashboard(page, { engine: engine({ cameras }) }, "/cameras/c1");
  await expect(page.getByText("bambu://192.168.1.9").first()).toBeVisible();
  await page.getByRole("tab", { name: /^Cameras/ }).click();
  await expect(page.getByText("rtsp://shed/live").first()).toBeVisible();
});

test("a crop wider than a square shows the squares the model scores and says what it costs", async ({ page }) => {
  await dashboard(page, { engine: engine({ cameras: [camera({ crop: { x: 0, y: 0, w: 1, h: 1 } })] }) }, "/cameras/c1");
  const editor = page.getByRole("main");
  await expect(editor.getByText("The model scores this crop as 2 overlapping squares, which takes 2 times the work.")).toBeVisible();
  await expect(editor.locator(".border-dashed")).toHaveCount(2);

  await editor.getByRole("button", { name: "Edit crop", exact: true }).click();
  const shape = editor.getByRole("group", { name: "Crop shape" });
  const warning = editor.getByText("Square crops tend to do better at spotting defects than wide ones.");
  await expect(shape.getByRole("button", { name: "Freeform" })).toHaveAttribute("aria-pressed", "true");
  await expect(warning).toBeVisible();
  await shape.getByRole("button", { name: "Square" }).click();
  await expect(warning).toBeHidden();
  await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
  const square = (await lastSent(page, "camera.update")).patch.crop;
  expect(square.w * (16 / 9)).toBeCloseTo(square.h, 2);
  expect(square.x).toBeCloseTo((1 - 9 / 16) / 2, 2);

  await editor.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(editor.getByText("The model only watches this square until you crop the camera")).toBeVisible();
  await expect(editor.locator(".border-dashed")).toHaveCount(0);
});

test("a new crop is square until freeform is chosen, which warns that it might detect worse", async ({ page }) => {
  await dashboard(page, {}, "/cameras/c1");
  const editor = page.getByRole("main");
  await editor.getByRole("button", { name: "Set crop", exact: true }).click();
  const shape = editor.getByRole("group", { name: "Crop shape" });
  await expect(shape.getByRole("button", { name: "Square" })).toHaveAttribute("aria-pressed", "true");
  await expect(editor.getByText(/Square crops tend to do better/)).toHaveCount(0);
  await shape.getByRole("button", { name: "Freeform" }).click();
  await expect(editor.getByRole("status").filter({ hasText: "A freeform crop still works, but detection might be worse." })).toBeVisible();
  await editor.getByRole("button", { name: "Done", exact: true }).click();
  await expect(shape).toBeHidden();
});

test("a feed that has no size yet leaves the crop square where it can be dragged", async ({ page }) => {
  await dashboard(page, {}, "/cameras/c1");
  const feed = page.locator(".ReactCrop video");
  await feed.dispatchEvent("loadedmetadata");
  await page.getByRole("button", { name: "Set crop", exact: true }).click();
  const selection = page.locator(".ReactCrop__crop-selection");
  await expect(selection).toBeVisible();
  await feed.evaluate((video) => {
    Object.defineProperties(video, { videoWidth: { value: 400 }, videoHeight: { value: 300 } });
    video.dispatchEvent(new Event("resize"));
  });
  await expect.poll(async () => (await selection.boundingBox())!.width / (await feed.boundingBox())!.width).toBeCloseTo(0.75, 1);
  await selection.scrollIntoViewIfNeeded();
  const before = (await selection.boundingBox())!;
  await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width / 2 - 80, before.y + before.height / 2, { steps: 5 });
  await page.mouse.up();
  expect((await selection.boundingBox())!.x).toBeLessThan(before.x - 40);
  await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
  expect((await sent(page, "camera.update")).patch.crop.x).toBeLessThan(0.2);
});

test("a camera's page shows one uncropped feed with the crop button on it", async ({ page }) => {
  await dashboard(page, { engine: engine({ cameras: [camera({ crop: { x: 0.25, y: 0, w: 0.5, h: 1 } })] }) }, "/cameras/c1");
  await expect(page.locator("main video")).toHaveCount(1);
  await expect(page.locator("main canvas")).toHaveCount(0);
  const feed = (await page.locator("main .feed").boundingBox())!;
  const button = (await page.getByRole("button", { name: "Edit crop", exact: true }).boundingBox())!;
  expect(button.y).toBeGreaterThan(feed.y);
  expect(button.y + button.height).toBeLessThan(feed.y + feed.height);
  expect(button.x + button.width).toBeLessThan(feed.x + feed.width);
});

test("the selected monitor's risk bar keeps its width when the score drops to one digit", async ({ page }) => {
  await dashboard(page, { history: { m1: [{ ts: 1, score: 0.12 }] } });
  const bar = page.getByRole("region", { name: "Prusa, selected monitor" }).getByRole("img", { name: /^risk/ }).locator("> span").last();
  const before = (await bar.boundingBox())!;
  await page.evaluate(() => (window as any).__pg.setState({ history: { m1: [{ ts: 2, score: 0.09 }] } }));
  await expect(page.getByRole("region", { name: "Prusa, selected monitor" }).getByRole("img", { name: "risk 9%" })).toBeVisible();
  expect(await bar.boundingBox()).toEqual(before);
});

test("the page fits the screen, with the fleet and each list scrolling on their own", async ({ page }) => {
  const monitors = Array.from({ length: 8 }, (_, index) => monitor({ id: `m${index}`, name: `Printer ${index}` }));
  const prints = Array.from({ length: 30 }, (_, index) => ({ id: `f${index}`, name: `part ${index}`, filename: `part${index}.gcode`, ext: "gcode", size: 1000, printer_ids: [], uploaded: index, meta: {}, thumbnail: null }));
  await dashboard(page, { engine: engine({ monitors, prints }) });
  const hero = page.getByRole("region", { name: "Printer 0, selected monitor" });
  const heroTop = (await hero.boundingBox())!.y;
  const lastMonitor = page.getByRole("link", { name: "Printer 7", exact: true });
  await expect(lastMonitor).not.toBeInViewport();
  await lastMonitor.scrollIntoViewIfNeeded();
  await expect(lastMonitor).toBeInViewport();
  expect((await hero.boundingBox())!.y).toBe(heroTop);
  await expect(page.getByRole("heading", { name: /^Fleet/ })).toBeInViewport();

  await routeTo(page, "/prints");
  const title = page.getByRole("heading", { name: "Prints", level: 1 });
  const titleTop = (await title.boundingBox())!.y;
  const lastPrint = page.locator("main .list-row").last();
  await expect(lastPrint).not.toBeInViewport();
  await lastPrint.scrollIntoViewIfNeeded();
  await expect(lastPrint).toBeInViewport();
  expect((await title.boundingBox())!.y).toBe(titleTop);
  expect(await page.evaluate(() => document.scrollingElement!.scrollHeight <= innerHeight)).toBe(true);
});

test("the divider, its arrow keys and the layout buttons resize the fleet, and the size is remembered", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const state = { engine: engine({ monitors: [monitor(), monitor({ id: "m2", name: "MK4" })] }) };
  await dashboard(page, state);
  const fleetTop = async () => (await page.getByRole("heading", { name: /^Fleet/ }).boundingBox())!.y;
  const divider = page.getByRole("separator", { name: "Selected monitor height" });
  const start = await fleetTop();
  const handle = (await divider.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2, handle.y - 120, { steps: 6 });
  await page.mouse.up();
  expect(start - (await fleetTop())).toBeGreaterThan(100);
  expect(start - (await fleetTop())).toBeLessThan(140);

  const dragged = await fleetTop();
  await divider.press("ArrowDown");
  expect(await fleetTop()).toBeGreaterThan(dragged);

  await page.getByRole("button", { name: "Layout", exact: true }).click();
  const beforeTaller = await fleetTop();
  await page.getByRole("button", { name: "Taller", exact: true }).click();
  expect(await fleetTop()).toBeLessThan(beforeTaller);

  const kept = await fleetTop();
  await page.reload();
  await dashboard(page, state);
  expect(await fleetTop()).toBe(kept);
});

test("the fleet can't grow over the selected monitor's risk, and what's pinned under it stays in view", async ({ page }) => {
  await dashboard(page, { engine: engine({ monitors: [monitor(), monitor({ id: "m2", name: "MK4" })] }) });
  const handle = (await page.getByRole("separator", { name: "Selected monitor height" }).boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2, 0, { steps: 8 });
  await page.mouse.up();
  const hero = page.getByRole("region", { name: "Prusa, selected monitor" });
  const risk = (await hero.getByRole("img", { name: /^risk/ }).boundingBox())!;
  const pinned = hero.getByText("Bind a printer to pause or cancel a failing print.");
  await expect(pinned).toBeInViewport();
  expect(risk.y + risk.height).toBeLessThan((await pinned.boundingBox())!.y);
});

test("on a phone the fleet stays at the bottom of the screen while the selected monitor scrolls above it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const monitors = Array.from({ length: 6 }, (_, index) => monitor({ id: `m${index}`, name: `Printer ${index}` }));
  await dashboard(page, { engine: engine({ monitors }) });
  const fleet = page.getByRole("heading", { name: /^Fleet/ });
  await expect(fleet).toBeInViewport();
  const fleetTop = (await fleet.boundingBox())!.y;
  await page.getByRole("link", { name: "Edit", exact: true }).scrollIntoViewIfNeeded();
  await page.getByRole("link", { name: "Printer 5", exact: true }).scrollIntoViewIfNeeded();
  expect((await fleet.boundingBox())!.y).toBe(fleetTop);
  await expect(page.getByRole("navigation", { name: "Primary" }).last()).toBeInViewport();
  expect(await page.evaluate(() => document.scrollingElement!.scrollHeight <= innerHeight)).toBe(true);
});

test("a quarter turn keeps the crop a square of the same size and centre, and the preview keeps its size", async ({ page }) => {
  const square = { x: (1 - 9 / 16) / 2, y: 0, w: 9 / 16, h: 1 };
  await dashboard(page, { engine: engine({ cameras: [camera({ crop: square })] }) }, "/cameras/c1");
  const stage = page.locator("main .ReactCrop").locator("xpath=..");
  const before = (await stage.boundingBox())!;
  const turn = async (degrees: string) => {
    await page.getByRole("radio", { name: degrees }).check();
    await page.evaluate(() => (window as any).__pg.getState().flushUpdates());
    return (await lastSent(page, "camera.update")).patch;
  };

  const turned = await turn("90°");
  expect(turned.rotation).toBe(90);
  expect(turned.crop.w).toBeCloseTo(1, 5);
  expect(turned.crop.h).toBeCloseTo(9 / 16, 5);
  expect(turned.crop.y).toBeCloseTo((1 - 9 / 16) / 2, 5);
  await emit(page, { event: "state", ...engine({ cameras: [camera({ rotation: 90, crop: turned.crop })] }) });
  expect(await stage.boundingBox()).toEqual(before);
  await page.getByRole("button", { name: "Edit crop", exact: true }).click();
  await expect(page.getByRole("button", { name: "Square" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Done", exact: true }).click();

  expect(await turn("270°")).toEqual({ rotation: 270 });
});
