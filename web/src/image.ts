import { useEffect } from "react";
import { bridge } from "./local";
import { hlsUrl, playHls } from "./stream";
import type { Camera } from "./types";

export function useVideoStream(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  camera: Camera | undefined,
  mode: string,
): void {
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !camera) return;
    if (mode === "local") {
      video.srcObject = bridge.getStream(camera.id);
      void video.play().catch(() => {});
      return () => {
        video.srcObject = null;
      };
    }
    const path = camera.source.kind === "path" ? camera.source.path! : camera.id;
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
    rotation?: number;
  },
): void {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  const rotation = ((((opts.rotation ?? 0) % 360) + 360) % 360);
  const swap = rotation === 90 || rotation === 270;
  const rw = swap ? vh : vw;
  const rh = swap ? vw : vh;
  const cx = opts.crop ? opts.crop.x * rw : 0;
  const cy = opts.crop ? opts.crop.y * rh : 0;
  const cropW = opts.crop ? opts.crop.w * rw : rw;
  const cropH = opts.crop ? opts.crop.h * rh : rh;
  const cw = canvas.parentElement?.clientWidth || cropW;
  const ch = canvas.parentElement?.clientHeight || cropH;
  const scale = Math.min(cw / cropW, ch / cropH);
  const dw = Math.round(cropW * scale);
  const dh = Math.round(cropH * scale);
  if (canvas.width !== dw || canvas.height !== dh) {
    canvas.width = dw;
    canvas.height = dh;
    canvas.style.width = `${dw}px`;
    canvas.style.height = `${dh}px`;
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(scale, scale);
  ctx.translate(-cx, -cy);
  if (rotation === 90) {
    ctx.translate(rw, 0);
    ctx.rotate(Math.PI / 2);
  } else if (rotation === 180) {
    ctx.translate(rw, rh);
    ctx.rotate(Math.PI);
  } else if (rotation === 270) {
    ctx.translate(0, rh);
    ctx.rotate((3 * Math.PI) / 2);
  }
  ctx.drawImage(video, 0, 0);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const image = ctx.getImageData(0, 0, dw, dh);
  adjust(image, opts.brightness, opts.contrast, opts.sharpness);
  ctx.putImageData(image, 0, 0);
}
