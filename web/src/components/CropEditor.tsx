import { useEffect, useRef, useState } from "react";
import ReactCrop, { type PercentCrop } from "react-image-crop";
import { renderVideoFrame, useVideoStream } from "../image";
import type { Camera, Crop } from "../types";

const MIN_SIZE_PX = 32;

function watchedSquare(crop: Crop | null, frameAspect: number): Crop {
  const region = crop ?? { x: 0, y: 0, w: 1, h: 1 };
  const w = Math.min(region.w, region.h / frameAspect);
  const h = w * frameAspect;
  return { x: region.x + (region.w - w) / 2, y: region.y + (region.h - h) / 2, w, h };
}

function toPercent(crop: Crop): PercentCrop {
  return { unit: "%", x: crop.x * 100, y: crop.y * 100, width: crop.w * 100, height: crop.h * 100 };
}

function fromPercent(crop: PercentCrop): Crop {
  return { x: crop.x / 100, y: crop.y / 100, w: crop.width / 100, h: crop.height / 100 };
}

export function CropEditor({
  camera,
  mode,
  crop,
  rotation,
  onChange,
}: {
  camera: Camera;
  mode: string;
  crop: Crop | null;
  rotation: number;
  onChange: (crop: Crop | null) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PercentCrop | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  const brightness = camera.brightness ?? 1;
  const contrast = camera.contrast ?? 1;
  const sharpness = camera.sharpness ?? 0;
  const needsCanvas = brightness !== 1 || contrast !== 1 || sharpness > 0 || rotation !== 0;
  const swap = rotation === 90 || rotation === 270;
  const frameAspect = dims ? (swap ? dims.h / dims.w : dims.w / dims.h) : 16 / 9;
  const watched = toPercent(watchedSquare(crop, frameAspect));

  useVideoStream(videoRef, camera, mode);

  useEffect(() => {
    if (!needsCanvas) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    let frame = 0;
    const tick = () => {
      if (video.readyState >= 2 && video.videoWidth > 0) {
        renderVideoFrame(ctx, video, canvas, { brightness, contrast, sharpness, rotation });
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [camera.id, needsCanvas, brightness, contrast, sharpness, rotation]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="label">Crop region</span>
        <div className="flex gap-2">
          {editing ? (
            <>
              <button
                className="btn !py-1 !px-2.5 !text-[0.62rem]"
                onClick={() => {
                  onChange(null);
                  setEditing(false);
                }}
              >
                Reset
              </button>
              <button className="btn btn-primary !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setEditing(false)}>
                Done
              </button>
            </>
          ) : (
            <button
              className="btn !py-1 !px-2.5 !text-[0.62rem]"
              onClick={() => {
                setDraft(watched);
                setEditing(true);
              }}
            >
              {crop ? "Edit crop" : "Set crop"}
            </button>
          )}
        </div>
      </div>
      <ReactCrop
        className="ReactCrop--no-animate"
        style={{ display: "block" }}
        crop={editing && draft ? draft : watched}
        aspect={1}
        minWidth={MIN_SIZE_PX}
        keepSelection
        disabled={!editing}
        onChange={(_, percent) => setDraft(percent)}
        onComplete={(_, percent) => onChange(fromPercent(percent))}
      >
        <div
          className={`relative bg-ink-0 overflow-hidden select-none ${editing ? "touch-none" : ""}`}
          style={{ aspectRatio: frameAspect }}
        >
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            onLoadedMetadata={(e) => setDims({ w: e.currentTarget.videoWidth, h: e.currentTarget.videoHeight })}
            className={`absolute inset-0 w-full h-full object-contain pointer-events-none ${needsCanvas ? "invisible" : ""}`}
          />
          {needsCanvas && <canvas ref={canvasRef} className="absolute inset-0 m-auto pointer-events-none" />}
        </div>
      </ReactCrop>
      <p className="text-[0.7rem] leading-snug text-text-2">
        The model only watches this square, so frame it tightly around the print.
      </p>
    </div>
  );
}
