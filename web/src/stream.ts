import Hls from "hls.js";
import { cameraApi } from "./media";
import type { Camera } from "./types";

const RECORDER_MIMES = [
  "video/mp4;codecs=avc1",
  "video/webm;codecs=h264",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
];

const PUBLISH_RECONNECT_MS = 2000;
const PUBLISHERS_KEY = "pg-publishers";

export const published = new Map<string, () => void>();

function loadPublishers(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(PUBLISHERS_KEY) || "{}");
  } catch {
    return {};
  }
}

function writePublishers(all: Record<string, string>): void {
  try {
    localStorage.setItem(PUBLISHERS_KEY, JSON.stringify(all));
  } catch {
    /* private-mode storage is unwritable; live publishing still works, only resume is lost */
  }
}

function persistPublisher(path: string, deviceId: string): void {
  writePublishers({ ...loadPublishers(), [path]: deviceId });
}

function forgetPublisher(path: string): void {
  const all = loadPublishers();
  delete all[path];
  writePublishers(all);
}

export function hlsUrl(path: string): string {
  return `/hls/${path}/index.m3u8`;
}

export function playHls(video: HTMLVideoElement, url: string): () => void {
  if (!Hls.isSupported()) {
    video.src = url;
    void video.play().catch(() => {});
    return () => {
      video.removeAttribute("src");
      video.load();
    };
  }
  let hls: Hls | null = null;
  let retry: number | undefined;
  const start = () => {
    hls = new Hls({
      liveSyncDuration: 5,
      backBufferLength: 0,
    });
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) {
        hls?.destroy();
        retry = window.setTimeout(start, 3000);
      }
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    void video.play().catch(() => {});
  };
  start();
  return () => {
    clearTimeout(retry);
    hls?.destroy();
  };
}

export async function publishStream(
  path: string,
  deviceId: string,
  onDown?: (reason: string) => void,
): Promise<{ stop: () => void; hlsPlayable: boolean }> {
  const mime = RECORDER_MIMES.find((m) => MediaRecorder.isTypeSupported(m));
  if (!mime) throw new Error("this browser cannot record video");
  const stream = await cameraApi().getUserMedia({
    video: { deviceId: { exact: deviceId }, frameRate: { ideal: 30, max: 30 } },
    audio: false,
  });
  persistPublisher(path, deviceId);

  let stopped = false;
  let recorder: MediaRecorder | null = null;
  let socket: WebSocket | null = null;
  let retry: number | undefined;

  const stopRecorder = () => {
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recorder = null;
  };

  const connect = () => {
    const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/publish/${path}`);
    socket = sock;
    sock.onopen = () => {
      const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 1_000_000 });
      rec.ondataavailable = (event) => {
        if (event.data.size && sock.readyState === WebSocket.OPEN) sock.send(event.data);
      };
      rec.start(100);
      recorder = rec;
    };
    sock.onclose = (event) => {
      stopRecorder();
      if (stopped) return;
      if (event.reason) onDown?.(event.reason);
      retry = window.setTimeout(connect, PUBLISH_RECONNECT_MS);
    };
  };
  connect();

  const stop = () => {
    stopped = true;
    clearTimeout(retry);
    stopRecorder();
    stream.getTracks().forEach((t) => t.stop());
    socket?.close();
    published.delete(path);
    forgetPublisher(path);
  };
  published.set(path, stop);
  return { stop, hlsPlayable: !mime.endsWith("vp8") };
}

export function stopPublishing(path: string): void {
  published.get(path)?.();
  forgetPublisher(path);
}

export async function resumePublishers(cameras: Camera[], onDown?: (reason: string) => void): Promise<void> {
  const want = loadPublishers();
  for (const camera of cameras) {
    const path = camera.source.path;
    if (!path || !(path in want) || published.has(path)) continue;
    try {
      await publishStream(path, want[path], onDown);
    } catch {
      /* device unavailable on resume; the camera stays offline until reopened */
    }
  }
}
