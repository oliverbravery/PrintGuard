import Hls from "hls.js";
import { cameraApi } from "./media";

const RECORDER_MIMES = [
  "video/mp4;codecs=avc1",
  "video/webm;codecs=h264",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
];

export const published = new Map<string, { stream: MediaStream; stop: () => void }>();

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
    hls = new Hls();
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
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/publish/${path}`);
  await new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("publish socket refused"));
  });
  const recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 1_000_000 });
  recorder.ondataavailable = (event) => {
    if (event.data.size && ws.readyState === WebSocket.OPEN) ws.send(event.data);
  };
  // A small timeslice flushes frames steadily; a large one batches them, which
  // starves the server's freshest-frame inference and jitters LL-HLS parts.
  recorder.start(100);
  ws.onclose = (event) => {
    if (event.reason && recorder.state === "recording") onDown?.(event.reason);
  };
  const stop = () => {
    published.delete(path);
    recorder.stop();
    stream.getTracks().forEach((t) => t.stop());
    ws.close();
  };
  published.set(path, { stream, stop });
  return { hlsPlayable: !mime.endsWith("vp8"), stop };
}
