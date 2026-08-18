import { log } from "./log";
import type { EngineState, Permission, PluginEffect, PluginNode, PluginRecord } from "./types";

const SANDBOX_URL = "plugin-sandbox.html";
const BOOT_TIMEOUT_MS = 8000;
const CALL_TIMEOUT_MS = 4000;
const MAX_EFFECTS = 32;

let nextCall = 0;

export interface HostHandlers {
  onView(id: string, tree: PluginNode | null, targets: Record<string, PluginNode | null>): void;
  onEffects(id: string, effects: PluginEffect[]): void;
  onStore(id: string, store: Record<string, unknown>): void;
  onFailure(id: string, reason: string): void;
}

export function projectState(engine: EngineState, granted: string[], permissions: Permission[]): Record<string, unknown> {
  const view: Record<string, unknown> = { mode: engine.mode, version: engine.version };
  for (const name of granted) {
    const fields = permissions.find((p) => p.id === name)?.fields;
    for (const [collection, keys] of Object.entries(fields ?? {})) {
      const items = (engine as unknown as Record<string, Record<string, unknown>[]>)[collection] ?? [];
      view[collection] = items.map((item) => Object.fromEntries(keys.filter((k) => k in item).map((k) => [k, item[k]])));
    }
  }
  return view;
}

export function projectEvent(
  event: Record<string, unknown>,
  events: Record<string, string[]>,
  granted: string[],
  permissions: Permission[],
): Record<string, unknown> | null {
  const name = String(event.event ?? "");
  const fields = events[name];
  if (!fields) return null;
  if (name === "state") return { event: name, ...projectState(event as unknown as EngineState, granted, permissions) };
  return { event: name, ...Object.fromEntries(fields.filter((field) => field in event).map((field) => [field, event[field]])) };
}

export function outboundRequest(id: string, request: Record<string, unknown> | undefined): Record<string, unknown> {
  const fields = request ?? {};
  return {
    cmd: "plugin.http",
    method: String(fields.method ?? "GET"),
    url: String(fields.url ?? ""),
    headers: fields.headers,
    json: fields.json,
    id,
  };
}

export function runsHere(platforms: string[] | undefined, host: string): boolean {
  return !platforms?.length || platforms.some((name) => host === name || host.startsWith(`${name}-`));
}

export function commandAllowed(command: string, granted: string[], permissions: Permission[]): boolean {
  const owner = permissions.find((p) => p.commands?.includes(command));
  return owner !== undefined && granted.includes(owner.id);
}

export class PluginHost {
  readonly id: string;
  private frame: HTMLIFrameElement;
  private pending = new Map<number, { resolve: (value: any) => void; reject: (reason: Error) => void; timer: number }>();
  private booted: Promise<void>;
  private dead = false;

  constructor(
    private record: PluginRecord,
    private file: string,
    private code: string,
    private handlers: HostHandlers,
  ) {
    this.id = record.id;
    this.frame = document.createElement("iframe");
    this.frame.src = SANDBOX_URL;
    this.frame.sandbox.add("allow-scripts");
    this.frame.allow = "";
    this.frame.title = `${record.manifest.name} sandbox`;
    this.frame.hidden = true;
    this.frame.style.display = "none";
    addEventListener("message", this.receive);
    document.body.appendChild(this.frame);
    this.booted = this.boot();
  }

  private boot(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("sandbox did not start")), BOOT_TIMEOUT_MS);
      const onBooted = (message: MessageEvent) => {
        if (message.source !== this.frame.contentWindow || message.data?.t !== "booted") return;
        removeEventListener("message", onBooted);
        clearTimeout(timer);
        this.send({ t: "init", code: this.code, store: this.record.config })
          .then(() => resolve())
          .catch(reject);
      };
      addEventListener("message", onBooted);
    }).catch((err: Error) => {
      this.fail(err.message);
      throw err;
    });
  }

  private receive = (message: MessageEvent) => {
    if (message.source !== this.frame.contentWindow) return;
    const { id, t } = message.data ?? {};
    const call = this.pending.get(id);
    if (!call) return;
    this.pending.delete(id);
    clearTimeout(call.timer);
    if (t === "failed") call.reject(new Error(String(message.data.message)));
    else call.resolve(message.data);
  };

  private send(payload: Record<string, unknown>): Promise<any> {
    const id = ++nextCall;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("plugin stopped answering"));
      }, CALL_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.frame.contentWindow?.postMessage({ ...payload, id }, "*");
    });
  }

  private async call(payload: Record<string, unknown>): Promise<void> {
    if (this.dead) return;
    try {
      await this.booted;
      const result = await this.send(payload);
      const targets = Object.fromEntries(
        Object.entries(result.targets ?? {}).map(([target, tree]) => [target, normalise(tree)]),
      );
      this.handlers.onView(this.id, normalise(result.tree), targets);
      this.handlers.onStore(this.id, result.store ?? {});
      this.handlers.onEffects(this.id, (result.effects ?? []).slice(0, MAX_EFFECTS));
    } catch (err) {
      this.fail(err instanceof Error ? err.message : String(err));
    }
  }

  update(state: Record<string, unknown>, targets: string[]): Promise<void> {
    return this.call({ t: "state", state, targets });
  }

  act(name: string, arg: unknown, state: Record<string, unknown>, targets: string[]): Promise<void> {
    return this.call({ t: "action", name, arg, state, targets });
  }

  event(event: Record<string, unknown>, state: Record<string, unknown>): Promise<void> {
    return this.call({ t: "event", event, state });
  }

  private fail(reason: string): void {
    if (this.dead) return;
    log("warn", `plugin ${this.id} (${this.file}) stopped: ${reason}`);
    this.handlers.onFailure(this.id, reason);
    this.close();
  }

  close(): void {
    this.dead = true;
    removeEventListener("message", this.receive);
    this.frame.remove();
    for (const call of this.pending.values()) clearTimeout(call.timer);
    this.pending.clear();
  }
}

const CONTAINERS = ["row", "col"];
const LEAVES = ["text", "chip", "camera", "button", "select"];
const MAX_NODES = 400;

export function normalise(raw: unknown, budget = { left: MAX_NODES }): PluginNode | null {
  if (!raw || typeof raw !== "object" || budget.left-- <= 0) return null;
  const node = raw as Record<string, unknown>;
  const type = String(node.type ?? "");
  if (CONTAINERS.includes(type)) {
    const children = Array.isArray(node.children) ? node.children : [];
    return { type, children: children.map((child) => normalise(child, budget)).filter(Boolean) as PluginNode[] } as PluginNode;
  }
  if (!LEAVES.includes(type)) return null;
  return {
    type,
    value: node.value === undefined ? undefined : String(node.value),
    label: node.label === undefined ? undefined : String(node.label).slice(0, 80),
    tone: ["ok", "warn", "bad", "accent"].includes(String(node.tone)) ? String(node.tone) : undefined,
    muted: node.muted === true,
    camera_id: node.camera_id === undefined ? undefined : String(node.camera_id),
    action: node.action === undefined ? undefined : String(node.action).slice(0, 60),
    arg: node.arg,
    options: Array.isArray(node.options)
      ? node.options.slice(0, 60).map((option: any) => ({ value: String(option?.value ?? option), label: String(option?.label ?? option) }))
      : undefined,
  } as PluginNode;
}
