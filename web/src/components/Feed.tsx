import { useEffect, useRef, useState } from "react";
import { registerFeed } from "../float";
import { renderVideoFrame, useVideoStream } from "../image";
import type { Camera } from "../types";

export function Feed({ camera, mode, active = true }: { camera: Camera | undefined; mode: string; active?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = useState(false);
  const brightness = camera?.brightness ?? 1;
  const contrast = camera?.contrast ?? 1;
  const sharpness = camera?.sharpness ?? 0;
  const crop = camera?.crop ?? null;
  const rotation = camera?.rotation ?? 0;
  const useCanvas = sharpness > 0 || crop !== null || brightness !== 1 || contrast !== 1 || rotation !== 0;

  useVideoStream(videoRef, camera, mode, active);

  useEffect(() => {
    const video = videoRef.current;
    return video && camera ? registerFeed(camera.id, video) : undefined;
  }, [camera?.id]);

  useEffect(() => setPlaying(false), [camera?.id, active]);

  useEffect(() => {
    if (!useCanvas) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    let frame = 0;
    const tick = () => {
      if (video.readyState >= 2 && video.videoWidth > 0) {
        renderVideoFrame(ctx, video, canvas, { brightness, contrast, sharpness, crop, rotation });
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [camera?.id, useCanvas, brightness, contrast, sharpness, crop, rotation]);

  return (
    <div className="relative aspect-video bg-ink-0 overflow-hidden">
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        onPlaying={() => setPlaying(true)}
        onWaiting={() => setPlaying(false)}
        onPause={() => setPlaying(false)}
        onEmptied={() => setPlaying(false)}
        onError={() => setPlaying(false)}
        className={useCanvas ? "absolute inset-0 w-full h-full object-contain invisible" : "absolute inset-0 w-full h-full object-contain"}
      />
      {useCanvas && <canvas ref={canvasRef} className="absolute inset-0 m-auto" />}
      {(!camera || !playing) && (
        <div className="absolute inset-0 grid place-items-center bg-ink-0/85 z-[2] pointer-events-none">
          <span className="mono text-[0.65rem] tracking-[0.2em] text-text-2 uppercase">
            {!camera ? "no camera bound" : camera.standby || camera.online ? "starting stream" : "no signal"}
          </span>
        </div>
      )}
    </div>
  );
}
