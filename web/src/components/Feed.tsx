import { useEffect, useRef } from "react";
import { bridge } from "../local";
import type { Camera } from "../types";
import { playWhep, whepBase } from "../webrtc";

function sharpen(data: ImageData, amount: number): void {
  const px = data.data;
  const w = data.width;
  const h = data.height;
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
        px[base + c] = Math.min(255, Math.max(0, src[base + c] + amount * (src[base + c] - blur)));
      }
    }
  }
}

export function Feed({ camera, mode, whep }: { camera: Camera | undefined; mode: string; whep: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const online = camera?.online ?? false;
  const brightness = camera?.brightness ?? 1;
  const contrast = camera?.contrast ?? 1;
  const sharpness = camera?.sharpness ?? 0;
  const cssFilter = brightness !== 1 || contrast !== 1 ? `brightness(${brightness}) contrast(${contrast})` : undefined;

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
    let stop: (() => void) | undefined;
    let cancelled = false;
    const path = camera.source.kind === "path" ? camera.source.path! : camera.id;
    playWhep(video, `${whepBase(whep)}/${path}/whep`)
      .then((fn) => {
        if (cancelled) fn();
        else stop = fn;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      stop?.();
      video.srcObject = null;
    };
  }, [camera?.id, camera?.online, mode, whep]);

  useEffect(() => {
    if (sharpness <= 0) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    let frame = 0;
    const tick = () => {
      if (video.readyState >= 2 && video.videoWidth > 0) {
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        const cw = canvas.parentElement?.clientWidth || vw;
        const ch = canvas.parentElement?.clientHeight || vh;
        const scale = Math.min(cw / vw, ch / vh);
        const dw = Math.round(vw * scale);
        const dh = Math.round(vh * scale);
        if (canvas.width !== dw || canvas.height !== dh) {
          canvas.width = dw;
          canvas.height = dh;
          canvas.style.width = `${dw}px`;
          canvas.style.height = `${dh}px`;
        }
        ctx.filter = cssFilter ?? "none";
        ctx.drawImage(video, 0, 0, dw, dh);
        ctx.filter = "none";
        const image = ctx.getImageData(0, 0, dw, dh);
        sharpen(image, sharpness);
        ctx.putImageData(image, 0, 0);
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [camera?.id, sharpness, cssFilter]);

  const sharpened = sharpness > 0;

  return (
    <div className="relative aspect-video bg-ink-0 overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        className={
          sharpened ? "absolute inset-0 w-full h-full object-contain invisible" : "absolute inset-0 w-full h-full object-contain"
        }
        style={!sharpened && cssFilter ? { filter: cssFilter } : undefined}
      />
      {sharpened && <canvas ref={canvasRef} className="absolute inset-0 m-auto" />}
      {(!camera || !online) && (
        <div className="absolute inset-0 grid place-items-center bg-ink-0/85 z-[2]">
          <span className="mono text-[0.65rem] tracking-[0.2em] text-text-2 uppercase">
            {camera ? "no signal" : "no camera bound"}
          </span>
        </div>
      )}
    </div>
  );
}
