import { create } from "zustand";
import { currentLayout } from "./layout";
import { bootLocal } from "./local";
import { log } from "./log";
import { resumePublishers } from "./stream";
import { applyTheme } from "./theme";
import type { Camera, CameraSource, EngineLink, EngineState, Layout, LayoutSection, Mode, Monitor, MonitorHistory, ScorePoint } from "./types";

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

function appendScore(history: Record<string, ScorePoint[]>, monitorId: string, point: ScorePoint): Record<string, ScorePoint[]> {
  const points = history[monitorId] ?? [];
  if ((points.at(-1)?.ts ?? 0) >= point.ts) return history;
  return { ...history, [monitorId]: [...points, point].slice(-HISTORY_LIMIT) };
}

function saveBase64(filename: string, base64: string, type: string) {
  const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(base64), (char) => char.charCodeAt(0))], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
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

export type DialogKind = "cameras" | "printers" | "monitor" | "settings" | "update" | "guide" | "report" | null;
export type SettingsTabId = "appearance" | "alerts" | "mqtt" | "updates" | "api" | "advanced";

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
  reportResult: { ok: boolean; error?: string } | null;
  pending: Record<string, { req_id: number; cmd: string }>;
  toasts: Toast[];
  detailId: string | null;
  statsMonitorId: string | null;
  historyData: Record<string, MonitorHistory | null>;
  snapshotCache: Record<string, string>;
  dialog: DialogKind;
  settingsTab: SettingsTabId | null;
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
  openSettings(tab?: SettingsTabId): void;
  openDetail(id: string | null): void;
  openStats(id: string | null): void;
  fetchSnapshot(monitorId: string, id: string): void;
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
    socket.onopen = () => log("info", "hub socket connected");
    socket.onmessage = (msg) => onEvent(JSON.parse(msg.data));
    socket.onclose = () => {
      if (!closed) {
        log("warn", "hub socket closed — reconnecting");
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
        let history = get().history;
        for (const monitor of server.monitors) {
          if (monitor.result) history = appendScore(history, monitor.id, monitor.result);
        }
        applyTheme(server.settings?.theme ?? "system", server.settings?.themes ?? []);
        set({ engine, history, optimistic, phase: "ready", ...(cleared ? { savedAt: Date.now() } : {}) });
        if (!resumed && get().mode === "hub") {
          resumed = true;
          void resumePublishers(server.cameras, (reason) => get().toast("error", `publishing stopped: ${reason}`));
        }
        break;
      }
      case "result":
        set((s) => ({ history: appendScore(s.history, event.monitor_id, { ts: event.ts, score: event.score }) }));
        if (get().statsMonitorId === event.monitor_id) get().send({ cmd: "history.get", monitor_id: event.monitor_id });
        break;
      case "alert": {
        const name = get().engine?.monitors.find((m) => m.id === event.monitor_id)?.name ?? "monitor";
        get().toast("alert", `Defect on ${name} — ${(event.score * 100).toFixed(0)}% (${event.action})`);
        break;
      }
      case "history":
        clearPending(event.req_id);
        set((s) => ({
          historyData: {
            ...s.historyData,
            [event.monitor_id]: { now: event.now, buckets: event.buckets, snaps: event.snaps, alerts: event.alerts, stats: event.stats },
          },
        }));
        break;
      case "snapshot":
        clearPending(event.req_id);
        set((s) => ({ snapshotCache: { ...s.snapshotCache, [event.id]: `data:image/jpeg;base64,${event.jpeg}` } }));
        break;
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
      case "report_sent":
        set({ reportResult: event });
        break;
      case "report_bundle":
        clearPending(event.req_id);
        saveBase64(event.filename, event.zip, "application/zip");
        get().toast("info", `Diagnostics saved as ${event.filename}`);
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
    log("info", `boot: ${mode} mode`);
    set({ mode, phase: "booting", bootMsg: mode === "hub" ? "Connecting to hub" : "Preparing local engine" });
    try {
      if (mode === "hub") {
        const link = connectHub(onEvent, () => set({ bootMsg: "Reconnecting" }));
        set({ link });
      } else {
        const link = await bootLocal(onEvent, (bootMsg) => {
          log("info", `local boot: ${bootMsg}`);
          set({ bootMsg });
        });
        set({ link });
      }
    } catch (err) {
      log("error", "boot failed:", err);
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
    reportResult: null,
    pending: {},
    toasts: [],
    detailId: null,
    statsMonitorId: null,
    historyData: {},
    snapshotCache: {},
    dialog: null,
    settingsTab: null,
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
      set({
        dialog,
        discovered: null,
        printerTest: null,
        notifyTest: null,
        reportResult: null,
        focusCameraId,
        createdToken: null,
        settingsTab: null,
      });
    },

    openSettings(settingsTab = "alerts") {
      get().flushUpdates();
      set({
        dialog: "settings",
        discovered: null,
        printerTest: null,
        notifyTest: null,
        reportResult: null,
        focusCameraId: null,
        createdToken: null,
        settingsTab,
      });
    },

    openDetail(detailId) {
      get().flushUpdates();
      set({ detailId, printerTest: null });
    },

    openStats(statsMonitorId) {
      get().flushUpdates();
      set({ statsMonitorId });
      if (statsMonitorId) get().send({ cmd: "history.get", monitor_id: statsMonitorId });
    },

    fetchSnapshot(monitorId, id) {
      if (get().snapshotCache[id]) return;
      get().send({ cmd: "snapshot.get", monitor_id: monitorId, id });
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
      log(kind === "error" ? "error" : kind === "alert" ? "warn" : "info", "toast:", text);
      const id = ++toastSeq;
      set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }));
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 6000);
    },
  };
});

(window as any).__pg = useStore;
