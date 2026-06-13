import { useEffect } from "react";
import { bridge } from "./local";
import { hlsUrl, playHls, published } from "./stream";
import type { Camera } from "./types";

export function useVideoStream(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  camera: Camera | undefined,
  mode: string,
): void {
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !camera) return;
    const path = camera.source.kind === "path" ? camera.source.path! : camera.id;
    const direct = mode === "local" ? bridge.getStream(camera.id) : published.get(path)?.stream;
    if (direct) {
      video.srcObject = direct;
      void video.play().catch(() => {});
      return () => {
        video.srcObject = null;
      };
    }
    let stop: (() => void) | undefined;
    const onVisibility = () => {
      stop?.();
      stop = undefined;
      if (!document.hidden) stop = playHls(video, hlsUrl(path));
    };
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop?.();
    };
  }, [videoRef, camera?.id, camera?.online, mode]);
}

export function adjust(data: ImageData, brightness: number, contrast: number, sharpness: number): void {
  const px = data.data;
  const w = data.width;
  const h = data.height;
  if (brightness !== 1 || contrast !== 1) {
    for (let i = 0; i < px.length; i += 4) {
      for (let c = 0; c < 3; c++) {
        let v = px[i + c] * brightness;
        v = (v - 128) * contrast + 128;
        px[i + c] = Math.min(255, Math.max(0, v));
      }
    }
  }
  if (sharpness > 0) {
    const src = new Uint8ClampedArray(px);
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const base = (y * w + x) * 4;
        for (let c = 0; c < 3; c++) {
          let blur = 0;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              blur += src[((y + dy) * w + (x + dx)) * 4 + c];
            }
          }
          blur /= 9;
          px[base + c] = Math.min(255, Math.max(0, src[base + c] + sharpness * (src[base + c] - blur)));
        }
      }
    }
  }
}

export function renderVideoFrame(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  opts: {
    brightness: number;
    contrast: number;
    sharpness: number;
    crop?: { x: number; y: number; w: number; h: number } | null;
  },
): void {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  const sx = opts.crop ? opts.crop.x * vw : 0;
  const sy = opts.crop ? opts.crop.y * vh : 0;
  const sw = opts.crop ? opts.crop.w * vw : vw;
  const sh = opts.crop ? opts.crop.h * vh : vh;
  const cw = canvas.parentElement?.clientWidth || sw;
  const ch = canvas.parentElement?.clientHeight || sh;
  const scale = Math.min(cw / sw, ch / sh);
  const dw = Math.round(sw * scale);
  const dh = Math.round(sh * scale);
  if (canvas.width !== dw || canvas.height !== dh) {
    canvas.width = dw;
    canvas.height = dh;
    canvas.style.width = `${dw}px`;
    canvas.style.height = `${dh}px`;
  }
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, dw, dh);
  const image = ctx.getImageData(0, 0, dw, dh);
  adjust(image, opts.brightness, opts.contrast, opts.sharpness);
  ctx.putImageData(image, 0, 0);
}
