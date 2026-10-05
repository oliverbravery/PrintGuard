import { log } from "./log";
import { sandboxFrame } from "./plugins";
import type { PluginEffect, PluginRecord } from "./types";

const PANEL_SANDBOX_URL = "plugin-panel.html";
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
  private frame: HTMLIFrameElement;
  private port: MessagePort;
  private dead = false;

  constructor(
    record: PluginRecord,
    container: HTMLElement,
    html: string,
    assets: Record<string, Blob>,
    state: Record<string, unknown>,
    private handlers: PanelHandlers,
  ) {
    this.id = record.id;
    const sandbox = sandboxFrame(PANEL_SANDBOX_URL, `${record.manifest.name} panel`, this.receive, (reason) => this.fail(reason));
    this.frame = sandbox.frame;
    this.port = sandbox.port;
    this.frame.className = "block h-24 w-full border-0 bg-transparent transition-[height] duration-150";
    container.appendChild(this.frame);
    this.port.postMessage({ t: "init", html, assets, state, theme: themeTokens(), store: record.config });
  }

  private receive = (data: any) => {
    if (data?.t === "effects") {
      this.handlers.onEffects(this.id, (data.effects ?? []).slice(0, MAX_EFFECTS));
    } else if (data?.t === "size") {
      this.frame.style.height = `${Math.min(Number(data.height) || 0, MAX_HEIGHT_PX)}px`;
    } else if (data?.t === "store") {
      this.handlers.onStore(this.id, data.store ?? {});
    } else if (data?.t === "failed") {
      this.fail(String(data.message));
    }
  };

  update(state: Record<string, unknown>, store?: Record<string, unknown>): void {
    this.port.postMessage({ t: "state", state, store, theme: themeTokens() });
  }

  event(event: Record<string, unknown>): void {
    this.port.postMessage({ t: "event", event });
  }

  private fail(reason: string): void {
    if (this.dead) return;
    log("warn", `plugin ${this.id} (panel.html) stopped: ${reason}`);
    this.handlers.onFailure(this.id, reason);
    this.close();
  }

  close(): void {
    this.dead = true;
    this.port.close();
    this.frame.remove();
  }
}
