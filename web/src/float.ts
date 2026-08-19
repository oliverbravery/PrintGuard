interface Feed {
  video: HTMLVideoElement;
  canvas(): HTMLCanvasElement | null;
}

const feeds = new Map<string, Feed>();
const drawn = new Map<string, HTMLVideoElement>();
const READY_WAIT_MS = 4000;

export function registerFeed(cameraId: string, feed: Feed): () => void {
  feeds.set(cameraId, feed);
  return () => {
    if (feeds.get(cameraId) === feed) feeds.delete(cameraId);
  };
}

export const floatSupported = (): boolean => document.pictureInPictureEnabled === true;

function fromCanvas(cameraId: string, canvas: HTMLCanvasElement): HTMLVideoElement {
  const video = drawn.get(cameraId) ?? document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.className = "fixed bottom-0 right-0 h-px w-px opacity-[0.01] pointer-events-none";
  video.srcObject = canvas.captureStream(15);
  if (!video.isConnected) document.body.appendChild(video);
  drawn.set(cameraId, video);
  return video;
}

function ready(video: HTMLVideoElement): Promise<boolean> {
  void video.play().catch(() => undefined);
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) return Promise.resolve(true);
  return new Promise((resolve) => {
    const settle = (ok: boolean) => {
      clearTimeout(timer);
      video.removeEventListener("loadedmetadata", onMetadata);
      resolve(ok);
    };
    const onMetadata = () => settle(true);
    const timer = setTimeout(() => settle(false), READY_WAIT_MS);
    video.addEventListener("loadedmetadata", onMetadata, { once: true });
  });
}

export async function floatCamera(cameraId: string, onClose: () => void): Promise<string | null> {
  const feed = feeds.get(cameraId);
  if (!feed) return "that camera is not on screen";
  if (!floatSupported()) return "this browser cannot float a video";
  const canvas = feed.canvas();
  const video = canvas ? fromCanvas(cameraId, canvas) : feed.video;
  if (!(await ready(video))) return "that feed has not started yet";
  try {
    await video.requestPictureInPicture();
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
  video.addEventListener("leavepictureinpicture", onClose, { once: true });
  return null;
}

export function unfloat(): void {
  if (document.pictureInPictureElement) void document.exitPictureInPicture().catch(() => undefined);
}
