import { log } from "./log";
import type { EngineState, Permission, PluginEffect, PluginNode, PluginRecord } from "./types";

const SANDBOX_URL = "plugin-sandbox.html";
const BOOT_TIMEOUT_MS = 8000;
const CALL_TIMEOUT_MS = 4000;
const MAX_EFFECTS = 32;

let nextCall = 0;

export interface PluginTarget {
  id: string;
  surface: string;
}

export interface HostHandlers {
  onView(id: string, tree: PluginNode | null, targets: Record<string, PluginNode | null>): void;
  onEffects(id: string, effects: PluginEffect[]): void;
  onStore(id: string, store: Record<string, unknown>): void;
  onFailure(id: string, reason: string): void;
}

export function projectState(engine: EngineState, granted: string[], permissions: Permission[]): Record<string, unknown> {
  const view: Record<string, unknown> = { version: engine.version };
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
  eventPermissions: Record<string, string> = {},
): Record<string, unknown> | null {
  const name = String(event.event ?? "");
  const fields = events[name];
  const needed = eventPermissions[name];
  if (!fields || (needed !== undefined && !granted.includes(needed))) return null;
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
    tag: String(fields.tag ?? ""),
    binary: fields.binary === true,
    id,
  };
}

export function outboundSocket(id: string, action: string, request: Record<string, unknown> | undefined): Record<string, unknown> {
  const fields = request ?? {};
  return {
    cmd: "plugin.socket",
    action,
    url: String(fields.url ?? ""),
    text: String(fields.text ?? ""),
    tag: String(fields.tag ?? ""),
    id,
  };
}

export const LINK_ACTIONS = ["call", "answer", "publish"];

export function outboundLink(id: string, action: string, request: Record<string, unknown> | undefined): Record<string, unknown> {
  const fields = request ?? {};
  return {
    cmd: `plugin.${action}`,
    to: String(fields.to ?? ""),
    channel: String(fields.channel ?? ""),
    tag: String(fields.tag ?? ""),
    call_id: String(fields.call_id ?? ""),
    body: fields.body,
    id,
  };
}

export function pluginFile(
  source: { repo?: string; path?: string; ref?: string },
  file: string | undefined,
): string | null {
  if (!source.repo || !source.ref || !file) return null;
  const prefix = source.path ? `${source.path}/` : "";
  return `https://raw.githubusercontent.com/${source.repo}/${source.ref}/${prefix}${file}`;
}

export function runsHere(platforms: string[] | undefined, host: string): boolean {
  return !platforms?.length || platforms.some((name) => host === name || host.startsWith(`${name}-`));
}

export function commandAllowed(command: string, granted: string[], permissions: Permission[]): boolean {
  const owner = permissions.find((p) => p.commands?.includes(command));
  return owner !== undefined && granted.includes(owner.id);
}

export function sandboxFrame(
  url: string,
  title: string,
  receive: (data: any) => void,
  fail: (reason: string) => void,
): { frame: HTMLIFrameElement; port: MessagePort; started: Promise<void> } {
  const frame = document.createElement("iframe");
  const { port1, port2 } = new MessageChannel();
  frame.src = url;
  frame.sandbox.add("allow-scripts");
  frame.allow = "";
  frame.title = title;
  port1.onmessage = (message) => receive(message.data);
  const started = new Promise<void>((resolve) => {
    const timer = window.setTimeout(() => fail("sandbox did not start"), BOOT_TIMEOUT_MS);
    let loaded = false;
    frame.addEventListener("load", () => {
      if (loaded) return fail("sandbox navigated away");
      loaded = true;
      clearTimeout(timer);
      frame.contentWindow?.postMessage({ t: "port" }, "*", [port2]);
      resolve();
    });
  });
  return { frame, port: port1, started };
}

export class PluginHost {
  readonly id: string;
  private frame: HTMLIFrameElement;
  private port: MessagePort;
  private pending = new Map<number, { resolve: (value: any) => void; reject: (reason: Error) => void; timer: number }>();
  private booted: Promise<void>;
  private dead = false;

  constructor(
    record: PluginRecord,
    code: string,
    assets: Record<string, string>,
    private handlers: HostHandlers,
  ) {
    this.id = record.id;
    const sandbox = sandboxFrame(SANDBOX_URL, `${record.manifest.name} sandbox`, this.receive, (reason) => this.fail(reason));
    this.frame = sandbox.frame;
    this.port = sandbox.port;
    this.frame.hidden = true;
    this.frame.style.display = "none";
    document.body.appendChild(this.frame);
    this.booted = sandbox.started.then(() => this.send({ t: "init", code, store: record.config, assets }));
    this.booted.catch((err: Error) => this.fail(err.message));
  }

  private receive = (data: any) => {
    const call = this.pending.get(data?.id);
    if (!call) return;
    this.pending.delete(data.id);
    clearTimeout(call.timer);
    if (data.t === "failed") call.reject(new Error(String(data.message)));
    else call.resolve(data);
  };

  private send(payload: Record<string, unknown>): Promise<any> {
    const id = ++nextCall;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("plugin stopped answering"));
      }, CALL_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.port.postMessage({ ...payload, id });
    });
  }

  private async call(payload: Record<string, unknown>): Promise<void> {
    if (this.dead) return;
    try {
      await this.booted;
      const result = await this.send(payload);
      if (result.targets) {
        const targets = Object.fromEntries(
          Object.entries(result.targets).map(([target, tree]) => [target, normalise(tree)]),
        );
        this.handlers.onView(this.id, normalise(result.tree), targets);
      }
      this.handlers.onStore(this.id, result.store ?? {});
      this.handlers.onEffects(this.id, (result.effects ?? []).slice(0, MAX_EFFECTS));
    } catch (err) {
      this.fail(err instanceof Error ? err.message : String(err));
    }
  }

  update(state: Record<string, unknown>, targets: PluginTarget[], store?: Record<string, unknown>): Promise<void> {
    return this.call({ t: "state", state, targets, store });
  }

  act(name: string, arg: unknown, state: Record<string, unknown>, targets: PluginTarget[]): Promise<void> {
    return this.call({ t: "action", name, arg, state, targets });
  }

  event(event: Record<string, unknown>, state: Record<string, unknown>, targets: PluginTarget[]): Promise<void> {
    return this.call({ t: "event", event, state, targets });
  }

  private fail(reason: string): void {
    if (this.dead) return;
    log("warn", `plugin ${this.id} stopped: ${reason}`);
    this.handlers.onFailure(this.id, reason);
    this.close();
  }

  close(): void {
    this.dead = true;
    this.port.close();
    this.frame.remove();
    for (const call of this.pending.values()) clearTimeout(call.timer);
    this.pending.clear();
  }
}

const CONTAINERS = ["row", "col"];
const LEAVES = ["text", "chip", "camera", "image", "float", "button", "select", "input", "toggle"];
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
    asset: node.asset === undefined ? undefined : String(node.asset),
    secret: node.secret === true,
    kind: node.kind === "number" ? "number" : undefined,
    placeholder: node.placeholder === undefined ? undefined : String(node.placeholder).slice(0, 60),
    on: node.on === true,
    action: node.action === undefined ? undefined : String(node.action).slice(0, 60),
    arg: node.arg,
    options: Array.isArray(node.options)
      ? node.options.slice(0, 60).map((option: any) => ({ value: String(option?.value ?? option), label: String(option?.label ?? option) }))
      : undefined,
  } as PluginNode;
}
