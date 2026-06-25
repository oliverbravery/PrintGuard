import { create } from "zustand";
import { currentLayout } from "./layout";
import { bootLocal } from "./local";
import { resumePublishers } from "./stream";
import { applyTheme } from "./theme";
import type { CameraSource, EngineLink, EngineState, Layout, LayoutSection, Mode, ScorePoint } from "./types";

const HISTORY_LIMIT = 240;

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
  setCustomising(on: boolean): void;
  mutateLayout(key: keyof Layout, fn: (section: LayoutSection) => LayoutSection): void;
  resetLayout(): void;
  chooseMode(mode: Mode): void;
  leaveMode(): void;
  send(cmd: Record<string, unknown>): void;
  isPending(cmd: string): boolean;
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

  const onEvent = (event: any) => {
    switch (event.event) {
      case "state": {
        clearPending(event.req_id);
        const settings = (event as EngineState).settings;
        applyTheme(settings?.theme ?? "system", settings?.themes ?? []);
        set({ engine: event as EngineState, phase: "ready" });
        if (!resumed && get().mode === "hub") {
          resumed = true;
          void resumePublishers((event as EngineState).cameras, (reason) => get().toast("error", `publishing stopped: ${reason}`));
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
        set({ discovering: false, testing: false, testingNotifier: null });
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
  if (stored) queueMicrotask(() => boot(stored));
  window.addEventListener("hashchange", () => location.reload());

  return {
    mode: stored,
    phase: stored ? "booting" : "pick",
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
      location.assign(location.pathname);
    },

    send(cmd) {
      const req_id = ++reqSeq;
      const cmdType = cmd.cmd as string;
      set((s) => ({ pending: { ...s.pending, [cmdType]: { req_id, cmd: cmdType } } }));
      get().link?.send({ ...cmd, req_id });
    },

    isPending(cmd) {
      return cmd in get().pending;
    },

    discover() {
      set({ discovered: null, discovering: true });
      get().send({ cmd: "discover" });
    },

    openDialog(dialog, focusCameraId = null) {
      set({ dialog, discovered: null, printerTest: null, notifyTest: null, focusCameraId, createdToken: null });
    },

    openDetail(detailId) {
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
