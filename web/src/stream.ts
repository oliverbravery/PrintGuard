import Hls from "hls.js";
import { cameraApi } from "./media";
import { readStored, writeStored } from "./storage";
import type { Camera } from "./types";

const RECORDER_MIMES = [
  "video/mp4;codecs=avc1",
  "video/webm;codecs=h264",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
];

const PUBLISH_RECONNECT_MS = 2000;
const PUBLISHERS_KEY = "pg-publishers";
const LIVE_RESYNC_S = 2;
const HLS_RETRY_MS = 3000;

export const published = new Map<string, () => void>();

function loadPublishers(): Record<string, string> {
  return JSON.parse(readStored(PUBLISHERS_KEY) || "{}");
}

function persistPublisher(path: string, deviceId: string): void {
  writeStored(PUBLISHERS_KEY, JSON.stringify({ ...loadPublishers(), [path]: deviceId }));
}

function forgetPublisher(path: string): void {
  const all = loadPublishers();
  delete all[path];
  writeStored(PUBLISHERS_KEY, JSON.stringify(all));
}

export function hlsUrl(path: string): string {
  return `/hls/${path}/index.m3u8`;
}

export function playHls(video: HTMLVideoElement, url: string, onRefused?: () => void): () => void {
  let hls: Hls | null = null;
  let retry: number | undefined;
  const resume = () => {
    const edge = hls?.liveSyncPosition ?? (video.seekable.length ? video.seekable.end(video.seekable.length - 1) : null);
    if (edge !== null && edge - video.currentTime > LIVE_RESYNC_S) video.currentTime = edge;
    void video.play().catch((refusal: DOMException) => {
      if (refusal.name === "NotAllowedError") onRefused?.();
    });
  };
  const retryLater = () => {
    clearTimeout(retry);
    retry = window.setTimeout(start, HLS_RETRY_MS);
  };
  const native = !Hls.isSupported();
  const start = () => {
    if (native) {
      video.src = url;
      return resume();
    }
    hls = new Hls({
      liveSyncDuration: 5,
      backBufferLength: 0,
    });
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) {
        hls?.destroy();
        retryLater();
      }
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    resume();
  };
  video.addEventListener("pause", resume);
  if (native) video.addEventListener("error", retryLater);
  start();
  return () => {
    video.removeEventListener("pause", resume);
    video.removeEventListener("error", retryLater);
    clearTimeout(retry);
    hls?.destroy();
    if (native) {
      video.removeAttribute("src");
      video.load();
    }
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
  let reported = "";

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
      if (event.reason && event.reason !== reported) onDown?.(event.reason);
      reported = event.reason;
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
  stream.getVideoTracks()[0].addEventListener("ended", () => {
    stop();
    onDown?.("the camera was disconnected");
  });
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
    await publishStream(path, want[path], onDown).catch(() => undefined);
  }
}
