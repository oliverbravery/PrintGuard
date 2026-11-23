import { log } from "./log";
import type { EngineLink } from "./types";

const RECONNECT_DELAY_MS = 1500;
const HUB_SILENCE_LIMIT_MS = 10_000;
const BLOCKED_PAGE_SLACK_MS = 2_000;

export function hubSocketUrl(path: string): string {
  const url = new URL(path, document.baseURI);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}

export function connectHub(onEvent: (event: any) => void, onUp: () => void, onDown: (wasUp: boolean) => void): EngineLink {
  let socket: WebSocket;
  const open = () => {
    const opening = new WebSocket(hubSocketUrl("api/ws"));
    socket = opening;
    let connected = false;
    let silence: ReturnType<typeof setTimeout>;
    const drop = () => {
      clearTimeout(silence);
      opening.onclose = opening.onmessage = null;
      log("warn", "hub socket closed, reconnecting");
      onDown(connected);
      setTimeout(open, RECONNECT_DELAY_MS);
    };
    const expectTick = () => {
      clearTimeout(silence);
      const armedAt = performance.now();
      silence = setTimeout(() => {
        if (performance.now() - armedAt > HUB_SILENCE_LIMIT_MS + BLOCKED_PAGE_SLACK_MS) return expectTick();
        log("warn", "hub socket went silent");
        opening.close();
        drop();
      }, HUB_SILENCE_LIMIT_MS);
    };
    opening.onopen = () => {
      log("info", "hub socket connected");
      connected = true;
      expectTick();
      onUp();
    };
    expectTick();
    opening.onmessage = (msg) => {
      expectTick();
      onEvent(JSON.parse(msg.data));
    };
    opening.onclose = drop;
  };
  open();
  return {
    send: (cmd) => {
      if (socket.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify(cmd));
      return true;
    },
  };
}
