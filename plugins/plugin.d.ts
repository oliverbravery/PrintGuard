declare global {
  type PluginTone = "ok" | "warn" | "bad" | "accent";

  type PluginNode =
    | { type: "row" | "col"; children: (PluginNode | null | false | undefined)[] }
    | { type: "text"; value: string; muted?: boolean }
    | { type: "chip"; value: string; tone?: PluginTone }
    | { type: "camera"; camera_id?: string }
    | { type: "button"; label: string; action: string; arg?: unknown }
    | { type: "select"; value?: string; label?: string; action: string; options: { value: string; label: string }[] };

  interface PluginMonitor {
    id: string;
    name: string;
    camera_id: string;
    printer_id: string;
    enabled: boolean;
    watching: boolean;
    threshold: number;
    result: { ts: number; score: number } | null;
    alert: { ts: number; score: number; action: string } | null;
  }

  interface PluginCamera {
    id: string;
    name: string;
    online: boolean;
    standby: boolean;
    in_use: boolean;
    max_fps: number;
    achieved_fps: number;
  }

  interface PluginPrinter {
    id: string;
    name: string;
    provider: string;
    online: boolean;
    device_state: { status: string; progress: number; job: string | null } | null;
  }

  interface PluginState {
    mode: "hub" | "local";
    version: string;
    monitors?: PluginMonitor[];
    cameras?: PluginCamera[];
    printers?: PluginPrinter[];
  }

  interface PluginEvents {
    result: { event: "result"; monitor_id: string; camera_id: string; score: number; prediction: "failure" | "success"; margin: number; ms: number; ts: number };
    alert: { event: "alert"; monitor_id: string; score: number; action: string; ts: number };
    warning: { event: "warning"; monitor_id?: string; message: string; recovered: boolean };
    device: { event: "device"; printer_id: string; status: string; progress: number; job: string | null };
    error: { event: "error"; message: string };
    state: { event: "state" } & PluginState;
    tick: { event: "tick" };
  }

  interface PluginRequest {
    method: string;
    path: string;
    query: Record<string, string>;
    headers: Record<string, string>;
    body: string | null;
  }

  interface PluginResponse {
    status?: number;
    type?: string;
    body?: string;
    headers?: { "set-cookie"?: string; location?: string; "cache-control"?: string };
  }

  interface PluginContext {
    state: PluginState;
    store: Record<string, any>;
    command(cmd: { cmd: string; [field: string]: unknown }): void;
    http(request: { method?: string; url: string; headers?: Record<string, string>; json?: unknown }): void;
    notify(text: string): void;
    float(on: boolean): void;
    log(text: string): void;
  }

  interface PluginApi {
    render(view: (ctx: PluginContext) => PluginNode | null): void;
    action(handler: (name: string, arg: any, ctx: PluginContext) => void): void;
    on<K extends keyof PluginEvents>(event: K, handler: (event: PluginEvents[K], ctx: PluginContext) => void): void;
    route(handler: (request: PluginRequest, ctx: PluginContext) => PluginResponse): void;
    gate(handler: (request: PluginRequest, ctx: PluginContext) => boolean): void;
  }

  const plugin: PluginApi;
}

export {};
