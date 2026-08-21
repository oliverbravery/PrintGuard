import { log } from "./log";
import type { PluginEffect, PluginRecord } from "./types";

export const PANEL_SANDBOX_URL = "plugin-panel.html";
const BOOT_TIMEOUT_MS = 8000;
const MAX_EFFECTS = 32;
const MAX_HEIGHT_PX = 900;
const THEME_TOKENS = [
  "--color-ink-0", "--color-ink-1", "--color-ink-2", "--color-ink-3",
  "--color-line-0", "--color-line-1",
  "--color-text-0", "--color-text-1", "--color-text-2",
  "--color-accent", "--color-ok", "--color-warn", "--color-bad", "--color-on-accent",
  "--font-display", "--font-body", "--font-mono",
];

export interface PanelHandlers {
  onEffects(id: string, effects: PluginEffect[]): void;
  onStore(id: string, store: Record<string, unknown>): void;
  onFailure(id: string, reason: string): void;
}

export function themeTokens(): Record<string, string> {
  const computed = getComputedStyle(document.body);
  return {
    ...Object.fromEntries(THEME_TOKENS.map((token) => [token, computed.getPropertyValue(token).trim()])),
    "color-scheme": computed.colorScheme,
  };
}

export class PluginPanelHost {
  readonly id: string;
  private booted = false;
  private dead = false;
  private queued: Record<string, unknown>[] = [];

  constructor(
    private record: PluginRecord,
    private frame: HTMLIFrameElement,
    private html: string,
    private assets: Record<string, Blob>,
    private state: Record<string, unknown>,
    private handlers: PanelHandlers,
  ) {
    this.id = record.id;
    addEventListener("message", this.receive);
    frame.contentWindow?.postMessage({ t: "hello" }, "*");
    window.setTimeout(() => {
      if (!this.booted) this.fail("panel did not start");
    }, BOOT_TIMEOUT_MS);
  }

  private receive = (message: MessageEvent) => {
    if (message.source !== this.frame.contentWindow || this.dead) return;
    const data = message.data ?? {};
    if (data.t === "booted") {
      this.booted = true;
      this.post({ t: "init", html: this.html, assets: this.assets, state: this.state, theme: themeTokens(), store: this.record.config });
      for (const message of this.queued.splice(0)) this.post(message);
    } else if (data.t === "effects") {
      this.handlers.onEffects(this.id, (data.effects ?? []).slice(0, MAX_EFFECTS));
    } else if (data.t === "size") {
      this.frame.style.height = `${Math.min(Number(data.height) || 0, MAX_HEIGHT_PX)}px`;
    } else if (data.t === "store") {
      this.handlers.onStore(this.id, data.store ?? {});
    } else if (data.t === "failed") {
      this.fail(String(data.message));
    }
  };

  private post(message: Record<string, unknown>): void {
    if (this.booted) this.frame.contentWindow?.postMessage(message, "*");
    else this.queued.push(message);
  }

  update(state: Record<string, unknown>, store?: Record<string, unknown>): void {
    this.state = state;
    this.post({ t: "state", state, store, theme: themeTokens() });
  }

  event(event: Record<string, unknown>): void {
    this.post({ t: "event", event });
  }

  private fail(reason: string): void {
    if (this.dead) return;
    log("warn", `plugin ${this.id} (panel.html) stopped: ${reason}`);
    this.handlers.onFailure(this.id, reason);
    this.close();
  }

  close(): void {
    this.dead = true;
    removeEventListener("message", this.receive);
  }
}
