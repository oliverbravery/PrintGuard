import { create } from "zustand";
import { currentLayout } from "./layout";
import { bootLocal } from "./local";
import { resumePublishers } from "./stream";
import { applyTheme } from "./theme";
import type { Camera, CameraSource, EngineLink, EngineState, Layout, LayoutSection, Mode, Monitor, ScorePoint } from "./types";

const HISTORY_LIMIT = 240;
const UPDATE_DEBOUNCE_MS = 250;
const updateTimers: Record<string, ReturnType<typeof setTimeout>> = {};

type OptimisticKind = "camera" | "monitor" | "settings";

interface OptimisticEntry {
  kind: OptimisticKind;
  id?: string;
  patch: Record<string, unknown>;
  reqId: number | null;
}

function applyOptimistic(engine: EngineState, overlay: Record<string, OptimisticEntry>): EngineState {
  let cameras = engine.cameras;
  let monitors = engine.monitors;
  let settings = engine.settings;
  for (const entry of Object.values(overlay)) {
    if (entry.kind === "camera") cameras = cameras.map((c) => (c.id === entry.id ? ({ ...c, ...entry.patch } as Camera) : c));
    else if (entry.kind === "monitor") monitors = monitors.map((m) => (m.id === entry.id ? ({ ...m, ...entry.patch } as Monitor) : m));
    else settings = { ...settings, ...entry.patch } as EngineState["settings"];
  }
  return { ...engine, cameras, monitors, settings };
}

function commandFor(entry: OptimisticEntry): Record<string, unknown> {
  if (entry.kind === "settings") return { cmd: "settings.update", patch: entry.patch };
  return { cmd: `${entry.kind}.update`, id: entry.id, patch: entry.patch };
}

function modeFromUrl(): Mode | null {
  const hash = location.hash.slice(1);
  return hash === "local" || hash === "hub" ? hash : null;
}

export interface Toast {
  id: number;
  kind: "info" | "alert" | "error";
  text: string;
}

export type DialogKind = "cameras" | "printers" | "monitor" | "settings" | "update" | "guide" | null;

interface PgStore {
  mode: Mode | null;
  phase: "pick" | "booting" | "ready" | "error";
  bootMsg: string;
  link: EngineLink | null;
  engine: EngineState | null;
  history: Record<string, ScorePoint[]>;
  discovered: CameraSource[] | null;
  discovering: boolean;
  printerTest: { ok: boolean; status?: string; error?: string } | null;
  testing: boolean;
  notifyTest: { provider: string; ok: boolean; error?: string } | null;
  testingNotifier: string | null;
  pending: Record<string, { req_id: number; cmd: string }>;
  toasts: Toast[];
  detailId: string | null;
  dialog: DialogKind;
  focusCameraId: string | null;
  createdToken: { name: string; secret: string } | null;
  customising: boolean;
  optimistic: Record<string, OptimisticEntry>;
  savedAt: number | null;
  setCustomising(on: boolean): void;
  mutateLayout(key: keyof Layout, fn: (section: LayoutSection) => LayoutSection): void;
  resetLayout(): void;
  chooseMode(mode: Mode): void;
  leaveMode(): void;
  send(cmd: Record<string, unknown>): number;
  isPending(cmd: string): boolean;
  updateCamera(id: string, patch: Record<string, unknown>): void;
  updateMonitor(id: string, patch: Record<string, unknown>): void;
  updateSettings(patch: Record<string, unknown>): void;
  flushUpdates(): void;
  discover(): void;
  openDialog(dialog: DialogKind, focusCameraId?: string | null): void;
  openDetail(id: string | null): void;
  clearCreatedToken(): void;
  testPrinter(provider: string, config: Record<string, string>): void;
  testNotifier(provider: string, config: Record<string, string>): void;
  toast(kind: Toast["kind"], text: string): void;
}

let toastSeq = 0;
let reqSeq = 0;
let resumed = false;

function connectHub(onEvent: (event: any) => void, onDown: () => void): EngineLink {
  let socket: WebSocket;
  let closed = false;
  const open = () => {
    socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`);
    socket.onmessage = (msg) => onEvent(JSON.parse(msg.data));
    socket.onclose = () => {
      if (!closed) {
        onDown();
        setTimeout(open, 1500);
      }
    };
  };
  open();
  return {
    send: (cmd) => socket.readyState === WebSocket.OPEN && socket.send(JSON.stringify(cmd)),
    close: () => {
      closed = true;
      socket.close();
    },
  };
}

export const useStore = create<PgStore>((set, get) => {
  const clearPending = (reqId?: number) => {
    if (reqId == null) return;
    set((s) => {
      const next = { ...s.pending };
      for (const [key, entry] of Object.entries(next)) {
        if (entry.req_id === reqId) delete next[key];
      }
      return { pending: next };
    });
  };

  const sendSilent = (cmd: Record<string, unknown>): number => {
    const req_id = ++reqSeq;
    get().link?.send({ ...cmd, req_id });
    return req_id;
  };

  const flushKey = (key: string) => {
    delete updateTimers[key];
    const entry = get().optimistic[key];
    if (!entry) return;
    const reqId = sendSilent(commandFor(entry));
    set((s) => (s.optimistic[key] ? { optimistic: { ...s.optimistic, [key]: { ...s.optimistic[key], reqId } } } : s));
  };

  const queueUpdate = (key: string, kind: OptimisticKind, id: string | undefined, patch: Record<string, unknown>) => {
    set((s) => {
      const prev = s.optimistic[key];
      const entry: OptimisticEntry = { kind, id, patch: { ...(prev?.patch ?? {}), ...patch }, reqId: null };
      const optimistic = { ...s.optimistic, [key]: entry };
      return { optimistic, savedAt: null, engine: s.engine ? applyOptimistic(s.engine, optimistic) : s.engine };
    });
    clearTimeout(updateTimers[key]);
    updateTimers[key] = setTimeout(() => flushKey(key), UPDATE_DEBOUNCE_MS);
  };

  const onEvent = (event: any) => {
    switch (event.event) {
      case "state": {
        clearPending(event.req_id);
        const server = event as EngineState;
        let optimistic = get().optimistic;
        const had = Object.keys(optimistic).length > 0;
        if (event.req_id != null && had) {
          optimistic = Object.fromEntries(Object.entries(optimistic).filter(([, e]) => e.reqId !== event.req_id));
        }
        const cleared = had && Object.keys(optimistic).length === 0;
        const engine = Object.keys(optimistic).length ? applyOptimistic(server, optimistic) : server;
        applyTheme(server.settings?.theme ?? "system", server.settings?.themes ?? []);
        set({ engine, optimistic, phase: "ready", ...(cleared ? { savedAt: Date.now() } : {}) });
        if (!resumed && get().mode === "hub") {
          resumed = true;
          void resumePublishers(server.cameras, (reason) => get().toast("error", `publishing stopped: ${reason}`));
        }
        break;
      }
      case "result":
        set((s) => {
          const points = [...(s.history[event.monitor_id] ?? []), { ts: event.ts, score: event.score }];
          return { history: { ...s.history, [event.monitor_id]: points.slice(-HISTORY_LIMIT) } };
        });
        break;
      case "alert": {
        const name = get().engine?.monitors.find((m) => m.id === event.monitor_id)?.name ?? "monitor";
        get().toast("alert", `Defect on ${name} — ${(event.score * 100).toFixed(0)}% (${event.action})`);
        break;
      }
      case "device":
        clearPending(event.req_id);
        set((s) =>
          s.engine
            ? {
                engine: {
                  ...s.engine,
                  printers: s.engine.printers.map((p) =>
                    p.id === event.printer_id
                      ? { ...p, device_state: { status: event.status, progress: event.progress, job: event.job } }
                      : p,
                  ),
                },
              }
            : s,
        );
        break;
      case "discovered":
        set({ discovered: event.sources, discovering: false });
        break;
      case "printer_test":
        set({ printerTest: event, testing: false });
        break;
      case "notify_test":
        set({ notifyTest: event, testingNotifier: null });
        break;
      case "token_created":
        set({ createdToken: { name: event.name, secret: event.token } });
        break;
      case "warning":
        get().toast(event.recovered ? "info" : "alert", event.message);
        break;
      case "error":
        get().toast("error", event.message);
        clearPending(event.req_id);
        set((s) => ({
          discovering: false,
          testing: false,
          testingNotifier: null,
          optimistic:
            event.req_id != null
              ? Object.fromEntries(Object.entries(s.optimistic).filter(([, e]) => e.reqId !== event.req_id))
              : s.optimistic,
        }));
        break;
    }
  };

  const boot = async (mode: Mode) => {
    set({ mode, phase: "booting", bootMsg: mode === "hub" ? "Connecting to hub" : "Preparing local engine" });
    try {
      if (mode === "hub") {
        const link = connectHub(onEvent, () => set({ bootMsg: "Reconnecting" }));
        set({ link });
      } else {
        const link = await bootLocal(onEvent, (bootMsg) => set({ bootMsg }));
        set({ link });
      }
    } catch (err) {
      set({ phase: "error", bootMsg: String(err) });
    }
  };

  const stored = modeFromUrl();
  queueMicrotask(async () => {
    if (stored) return void boot(stored);
    const hubReady = await fetch("api/health").then((r) => r.ok).catch(() => false);
    if (hubReady) boot("hub");
    else set({ phase: "pick" });
  });
  window.addEventListener("hashchange", () => location.reload());

  return {
    mode: stored,
    phase: "booting",
    bootMsg: "",
    link: null,
    engine: null,
    history: {},
    discovered: null,
    discovering: false,
    printerTest: null,
    testing: false,
    notifyTest: null,
    testingNotifier: null,
    pending: {},
    toasts: [],
    detailId: null,
    dialog: null,
    focusCameraId: null,
    createdToken: null,
    customising: false,
    optimistic: {},
    savedAt: null,

    setCustomising(on) {
      set({ customising: on });
    },

    mutateLayout(key, fn) {
      const engine = get().engine;
      if (!engine) return;
      const base = currentLayout(engine.settings.layout);
      const layout: Layout = { ...base, [key]: fn(base[key]) };
      set({ engine: { ...engine, settings: { ...engine.settings, layout } } });
      get().send({ cmd: "settings.update", patch: { layout } });
    },

    resetLayout() {
      const engine = get().engine;
      if (!engine) return;
      set({ engine: { ...engine, settings: { ...engine.settings, layout: undefined } } });
      get().send({ cmd: "settings.update", patch: { layout: {} } });
    },

    chooseMode(mode) {
      history.pushState(null, "", `#${mode}`);
      void boot(mode);
    },

    leaveMode() {
      get().flushUpdates();
      location.assign(location.pathname);
    },

    send(cmd) {
      const req_id = ++reqSeq;
      const cmdType = cmd.cmd as string;
      set((s) => ({ pending: { ...s.pending, [cmdType]: { req_id, cmd: cmdType } } }));
      get().link?.send({ ...cmd, req_id });
      return req_id;
    },

    isPending(cmd) {
      return cmd in get().pending;
    },

    updateCamera(id, patch) {
      queueUpdate(`camera:${id}`, "camera", id, patch);
    },

    updateMonitor(id, patch) {
      queueUpdate(`monitor:${id}`, "monitor", id, patch);
    },

    updateSettings(patch) {
      queueUpdate("settings", "settings", undefined, patch);
    },

    flushUpdates() {
      for (const key of Object.keys(updateTimers)) {
        clearTimeout(updateTimers[key]);
        flushKey(key);
      }
    },

    discover() {
      set({ discovered: null, discovering: true });
      get().send({ cmd: "discover" });
    },

    openDialog(dialog, focusCameraId = null) {
      get().flushUpdates();
      set({ dialog, discovered: null, printerTest: null, notifyTest: null, focusCameraId, createdToken: null });
    },

    openDetail(detailId) {
      get().flushUpdates();
      set({ detailId, printerTest: null });
    },

    clearCreatedToken() {
      set({ createdToken: null });
    },

    testPrinter(provider, config) {
      set({ printerTest: null, testing: true });
      get().send({ cmd: "printer.test", provider, config });
    },

    testNotifier(provider, config) {
      set({ notifyTest: null, testingNotifier: provider });
      get().send({ cmd: "notify.test", provider, config });
    },

    toast(kind, text) {
      const id = ++toastSeq;
      set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }));
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 6000);
    },
  };
});

(window as any).__pg = useStore;
