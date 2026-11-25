import { expect, type Page, type WebSocketRoute } from "@playwright/test";

export const camera = (over = {}) => ({
  id: "c1", name: "Workshop", source: { kind: "rtsp", url: "rtsp://camera" }, printer_id: null,
  max_fps: 30, detect_fps: 60, brightness: 1, contrast: 1, sharpness: 0, crop: null, rotation: 0,
  target_fps: 5, achieved_fps: 5, inferring: false, in_use: true, online: true, standby: false, last_result: null, ...over,
});

export const monitor = (over = {}) => ({
  id: "m1", name: "Prusa", camera_id: "c1", printer_id: "", enabled: true, threshold: 0.6, consecutive: 3,
  notify: true, on_defect: "pause", cooldown_s: 90, pause_on_camera_loss: false, watching: true, alert: null, ...over,
});

export const printer = (over = {}) => ({
  id: "p1", name: "Ender", provider: "octoprint", model: "", config: {}, online: true,
  device_state: { status: "printing", progress: 40, job: "cube.gcode", remaining_s: 600, nozzle: { actual: 210, target: 210 }, bed: { actual: 60, target: 60 } },
  ...over,
});

export const review = (over = {}) => ({
  id: "r1", monitor_id: "m1", status: "ready", started: 1, ended: 2, frames: 3, bytes: 0, alerts: 1, recording: null, timeline: [], chosen: 0, sent: 0, code: null, retry_at: null, ...over,
});

export const engine = (over = {}) => ({
  version: "test", update: null, cameras: [camera()], printers: [], prints: [], reviews: [], monitors: [monitor()],
  tokens: [], notifiers: [],
  integrations: [{ id: "octoprint", label: "OctoPrint", docs_url: "", formats: [], heater_control: true, schema: { properties: {} } }],
  settings: { notifiers: {}, update_check: true, theme: "dark", themes: [], layout: {}, preheat: [] },
  stats: { inference_device: "CPU", infer_ms: 1, capacity_fps: 1 },
  plugins: [], plugin_permissions: [], plugin_events: {}, plugin_assets: {}, ...over,
});

export async function dashboard(page: Page, state: Record<string, unknown> = {}, route = "/") {
  await page.routeWebSocket(/\/api\/ws$/, () => {});
  await page.goto(`/#${route}`);
  await page.waitForFunction(() => Boolean((window as any).__pg?.getState().link));
  await page.evaluate(
    (state) => {
      const win = window as any;
      win.__sent = [];
      win.__pg.setState({ phase: "ready", link: { send: (cmd: any) => win.__sent.push(cmd), close() {} }, ...state });
    },
    { engine: engine(), ...state },
  );
  if (state.phase !== "booting") await page.locator("main").waitFor({ state: "attached" });
}

export async function hub(page: Page, onCommand: (command: any, socket: WebSocketRoute) => void = () => {}, state = engine(), route = "/") {
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
  await page.goto(`/#${route}`);
  await expect(page.locator("main h1")).toBeAttached();
  return { sockets, commands };
}

export const pastDoublePress = (page: Page) => page.waitForTimeout(400);
export const sent = (page: Page, cmd: string) => page.evaluate((cmd) => (window as any).__sent.find((c: any) => c.cmd === cmd), cmd);
export const emit = (page: Page, event: Record<string, unknown>) => page.evaluate((event) => (window as any).__pgEvent(event), event);
