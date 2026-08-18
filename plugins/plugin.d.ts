declare global {
  /** Colour a `chip` node is drawn in. */
  type PluginChipTone = "ok" | "warn" | "bad" | "accent";

  /** One note in a sound, played with a fast attack and a decay to silence. */
  interface PluginTone {
    /** Pitch in hertz, 20 to 12000. */
    hz: number;
    /** How long it lasts in milliseconds, 10 at the least. */
    ms: number;
    /** Waveform, one of `sine`, `square`, `sawtooth` or `triangle`, and `sine` by default. */
    shape?: string;
    /** Start it with the tone before rather than after it, which is how a chord is built. */
    together?: boolean;
  }

  /**
   * One piece of a view. PrintGuard draws every node with its own components,
   * so a plugin inherits the dashboard's theme and can draw nothing else.
   */
  type PluginNode =
    /** Lays its children out left to right, or top to bottom. */
    | { type: "row" | "col"; children: (PluginNode | null | false | undefined)[] }
    /** A line of text. `muted` makes it secondary. */
    | { type: "text"; value: string; muted?: boolean }
    /** A small pill, for a status or a count. */
    | { type: "chip"; value: string; tone?: PluginChipTone }
    /** A live feed of a registered camera. Needs `camera:view`, and the video never enters the sandbox. */
    | { type: "camera"; camera_id?: string }
    /** An image you shipped, named as it appears in the manifest's `assets`. */
    | { type: "image"; asset: string; label?: string }
    /** A field the user types into, committed on blur or Enter. `secret` masks it. */
    | { type: "input"; value?: string; label?: string; action: string; kind?: "text" | "number"; placeholder?: string; secret?: boolean }
    /** A switch, handed `true` or `false` as the arg. */
    | { type: "toggle"; on?: boolean; label?: string; action: string }
    /** Calls your `action` handler with `action` as the name and `arg` as given. */
    | { type: "button"; label: string; action: string; arg?: unknown }
    /** Calls your `action` handler with the chosen option's value as the arg. */
    | { type: "select"; value?: string; label?: string; action: string; options: { value: string; label: string }[] };

  /** A monitor, as `state:read` allows you to see it. */
  interface PluginMonitor {
    id: string;
    name: string;
    /** The camera it watches, and the one a `camera` node should name. */
    camera_id: string;
    /** Empty when no printer is bound. */
    printer_id: string;
    enabled: boolean;
    /** Whether inference is actually running, which a printer that is not printing stands down. */
    watching: boolean;
    /** The score a frame must reach to count as a defect, 0 to 1. */
    threshold: number;
    /** The last score, or null before the first one. */
    result: { ts: number; score: number } | null;
    /** The alert in force, or null when nothing is wrong. */
    alert: { ts: number; score: number; action: string } | null;
  }

  /** A camera, as `state:read` allows you to see it. */
  interface PluginCamera {
    id: string;
    name: string;
    /** Whether the source is reachable. */
    online: boolean;
    /** Whether it is idling, kept open but not inferring. */
    standby: boolean;
    /** Whether a monitor is using it. */
    in_use: boolean;
    max_fps: number;
    /** What inference is managing, against the monitor's target. */
    achieved_fps: number;
  }

  /** A printer, as `state:read` allows you to see it. */
  interface PluginPrinter {
    id: string;
    name: string;
    /** The integration behind it, such as `octoprint` or `bambu`. */
    provider: string;
    online: boolean;
    /** Null until the service has been polled once. */
    device_state: { status: string; progress: number; job: string | null } | null;
  }

  /**
   * What your permissions let you read, refreshed for every call. A collection
   * is missing entirely unless a permission names it, and credentials, notifier
   * settings and API tokens are in no permission.
   */
  interface PluginState {
    /** `hub` for the self-hosted server, `local` for the browser. */
    mode: "hub" | "local";
    /** The PrintGuard version running. */
    version: string;
    monitors?: PluginMonitor[];
    cameras?: PluginCamera[];
    printers?: PluginPrinter[];
  }

  /** The events a worker can hook, and what each one carries. */
  interface PluginEvents {
    /** Every inference on a watched monitor, capped at 5 a second per monitor, before any threshold or streak logic. */
    result: { event: "result"; monitor_id: string; camera_id: string; score: number; prediction: "failure" | "success"; margin: number; ms: number; ts: number };
    /** A defect held long enough to act on. `action` is what PrintGuard did to the printer. */
    alert: { event: "alert"; monitor_id: string; score: number; action: string; ts: number };
    /** A watchdog condition, and again with `recovered` when it clears. */
    warning: { event: "warning"; monitor_id?: string; message: string; recovered: boolean };
    /** A printer's status changed. */
    device: { event: "device"; printer_id: string; status: string; progress: number; job: string | null };
    /** Anything that failed. */
    error: { event: "error"; message: string };
    /** The snapshot your permissions allow, once a second. */
    state: { event: "state" } & PluginState;
    /** Your own timer, as often as `tick_s` in the manifest asks. */
    tick: { event: "tick" };
  }

  /** A request to one of your routes, or one a gate is being asked about. */
  interface PluginRequest {
    method: string;
    path: string;
    query: Record<string, string>;
    /** Cookie, authorization, accept, content-type, x-forwarded-for and user-agent, where present. */
    headers: Record<string, string>;
    /** Null for a request without one, and capped at 64 KB. */
    body: string | null;
  }

  /** What a route hands back. Defaults to an empty 200 of `text/plain`. */
  interface PluginResponse {
    status?: number;
    /** Content type, such as `text/html`. */
    type?: string;
    body?: string;
    /** Only these three are passed on. */
    headers?: { "set-cookie"?: string; location?: string; "cache-control"?: string };
  }

  /**
   * Everything a plugin can reach. It performs nothing itself: each call asks
   * PrintGuard for something, which is checked against your granted
   * permissions before it happens.
   */
  interface PluginContext {
    /** What your permissions let you read, fresh for this call. */
    state: PluginState;
    /** The monitor this view is being drawn for, on the `monitor` and `settings` surfaces, and undefined for your panel. */
    target?: string;
    /** Which surface is being drawn, `monitor` or `settings`, alongside `ctx.target`. */
    surface?: string;
    /** The text files you shipped, keyed by name. Images and audio are not here, since only PrintGuard handles those. */
    assets: Record<string, string>;
    /** Your own data. Assign to it and PrintGuard saves it, up to 16 KB. */
    store: Record<string, any>;
    /**
     * Asks PrintGuard to run an engine command, such as
     * `{ cmd: "printer.action", id, action: "pause" }`. Every command maps to a
     * permission, and one you were not granted is refused and reported.
     */
    command(cmd: { cmd: string; [field: string]: unknown }): void;
    /** Asks PrintGuard to make an HTTP request for you. Needs `net`, and a URL on a host your manifest declares. */
    http(request: { method?: string; url: string; headers?: Record<string, string>; json?: unknown }): void;
    /** Raises a message on the dashboard. Needs `notify`, and does not use the user's alert channels. */
    notify(text: string): void;
    /**
     * Floats the camera your view last drew, in the browser's own
     * picture-in-picture window. Needs the `float` surface and a view that is
     * a single `camera` node.
     */
    float(on: boolean): void;
    /**
     * Sounds tones through the speakers of whoever is looking, one after the
     * next unless a tone says `together`. Needs `sound`, and stays quiet until
     * they have pressed something in the page. Four seconds is the most it
     * will play.
     */
    sound(tones: PluginTone[] | PluginTone): void;
    /** Plays an audio file you shipped, named as it appears in the manifest's `assets`. Needs `sound`. */
    sound(asset: string): void;
    /** Writes a line to PrintGuard's log. */
    log(text: string): void;
  }

  /**
   * Registers what your plugin does. `render` and `action` are the panel half
   * in `plugin.js`, the rest are the worker half in `worker.js`.
   */
  interface PluginApi {
    /**
     * Draws the view, again on every state change and after every action, so
     * keep it a plain function of `ctx`. On the `monitor` surface it is called
     * once more per monitor, with `ctx.target` naming which.
     */
    render(view: (ctx: PluginContext) => PluginNode | null): void;
    /** Handles a press or a choice, named by the node's `action` and given its `arg`. */
    action(handler: (name: string, arg: any, ctx: PluginContext) => void): void;
    /** Wakes the worker on an engine event. Name it in the manifest's `events` too, or it never fires. */
    on<K extends keyof PluginEvents>(event: K, handler: (event: PluginEvents[K], ctx: PluginContext) => void): void;
    /** Answers everything under `/plugins/<id>/` on the hub. Needs `routes`, and pages are served into a sandboxed origin. */
    route(handler: (request: PluginRequest, ctx: PluginContext) => PluginResponse): void;
    /** Approves or refuses every other request to the hub. Needs `gate`, and anything but `true` refuses. */
    gate(handler: (request: PluginRequest, ctx: PluginContext) => boolean): void;
  }

  /** Registers your plugin. In scope in `plugin.js` and `worker.js`, with nothing else beside it. */
  const plugin: PluginApi;
}

export {};
