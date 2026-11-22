import { useEffect, useRef, useState, type ReactNode, type SyntheticEvent } from "react";
import { registerFeed } from "../float";
import { renderVideoFrame, useVideoStream } from "../image";
import { useStore } from "../store";
import type { Camera } from "../types";

export function useCovered(): boolean {
  return useStore((s) => s.dialog !== null || s.staged.length > 0);
}

export function Feed({
  camera,
  active = true,
  compact = false,
  className = "",
  aspect,
  uncropped = false,
  onFrameSize,
  banner,
  children,
}: {
  camera: Camera | undefined;
  active?: boolean;
  compact?: boolean;
  className?: string;
  aspect?: number;
  uncropped?: boolean;
  onFrameSize?: (size: { w: number; h: number }) => void;
  banner?: ReactNode;
  children?: ReactNode;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = useState(false);
  const brightness = camera?.brightness ?? 1;
  const contrast = camera?.contrast ?? 1;
  const sharpness = camera?.sharpness ?? 0;
  const crop = uncropped ? null : (camera?.crop ?? null);
  const rotation = camera?.rotation ?? 0;
  const useCanvas = sharpness > 0 || crop !== null || brightness !== 1 || contrast !== 1 || rotation !== 0;

  const { streaming, refused } = useVideoStream(videoRef, camera, active);
  const idle = !camera || !playing;
  const tapToPlay = Boolean(camera) && active && refused && !playing;

  useEffect(() => {
    const video = videoRef.current;
    return video && camera ? registerFeed(camera.id, video) : undefined;
  }, [camera?.id]);

  useEffect(() => setPlaying(false), [camera?.id, streaming]);

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

  const reportSize = ({ currentTarget: video }: SyntheticEvent<HTMLVideoElement>) => {
    if (video.videoWidth) onFrameSize?.({ w: video.videoWidth, h: video.videoHeight });
  };

  return (
    <div
      data-camera={camera?.id}
      className={`feed relative overflow-hidden bg-ink-1 ${aspect ? "" : "aspect-video"} ${compact ? "border border-line-0" : ""} ${className}`}
      style={aspect ? { aspectRatio: aspect } : undefined}
    >
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
        onLoadedMetadata={reportSize}
        onResize={reportSize}
        className={useCanvas ? "absolute inset-0 w-full h-full object-contain invisible" : "absolute inset-0 w-full h-full object-contain"}
      />
      {useCanvas && <canvas ref={canvasRef} className="absolute inset-0 m-auto" />}
      {idle && <div className="pointer-events-none absolute inset-0 z-[2] bg-ink-0/85" />}
      <div className="pointer-events-none absolute inset-0 grid place-items-center">
        <div className="relative grid justify-items-center">
          {banner}
          <div className={banner ? "absolute top-full mt-2 w-max" : ""}>
            {idle && !tapToPlay && !compact && (
              <span className="mono relative z-[2] text-xs tracking-[0.12em] text-text-2 uppercase">
                {!camera ? "no camera bound" : !active ? "feed paused" : camera.standby || camera.online ? "starting stream" : "no signal"}
              </span>
            )}
            {tapToPlay && (
              <button className={`${compact ? "btn-inline" : "btn"} pointer-events-auto relative z-[3]`} onClick={() => void videoRef.current?.play().catch(() => undefined)}>
                {compact ? "Play" : "Tap to play"}
              </button>
            )}
          </div>
        </div>
      </div>
      {children}
    </div>
  );
}
