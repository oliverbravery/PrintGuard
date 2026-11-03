import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import ReactCrop, { type PercentCrop } from "react-image-crop";
import { useFocusKept } from "../a11y";
import { renderVideoFrame, useVideoStream } from "../image";
import type { Camera, Crop } from "../types";

const MIN_SIZE_PX = 32;
const LONGEST_RATIO = 4;
const SQUARE_OVERLAP = 0.2;

function middleSquare(frameAspect: number): Crop {
  const w = Math.min(1, 1 / frameAspect);
  const h = w * frameAspect;
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
}

function squareStarts(long: number, short: number): number[] {
  const span = Math.min(long, short * LONGEST_RATIO);
  const ratio = span / short;
  if (ratio <= 1 + SQUARE_OVERLAP) return [(long - short) / 2];
  const count = Math.ceil((ratio - SQUARE_OVERLAP) / (1 - SQUARE_OVERLAP));
  const step = (span - short) / (count - 1);
  return Array.from({ length: count }, (_, index) => (long - span) / 2 + index * step);
}

function scoredSquares(crop: Crop, frameAspect: number): Crop[] {
  const width = crop.w * frameAspect;
  if (width >= crop.h) return squareStarts(width, crop.h).map((start) => ({ x: crop.x + start / frameAspect, y: crop.y, w: crop.h / frameAspect, h: crop.h }));
  return squareStarts(crop.h, width).map((start) => ({ x: crop.x, y: crop.y + start, w: crop.w, h: width }));
}

function toPercent(crop: Crop): PercentCrop {
  return { unit: "%", x: crop.x * 100, y: crop.y * 100, width: crop.w * 100, height: crop.h * 100 };
}

function fromPercent(crop: PercentCrop): Crop {
  return { x: crop.x / 100, y: crop.y / 100, w: crop.width / 100, h: crop.height / 100 };
}

export function CropEditor({
  camera,
  crop,
  rotation,
  onChange,
}: {
  camera: Camera;
  crop: Crop | null;
  rotation: number;
  onChange: (crop: Crop | null) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [editing, setEditing] = useState(false);
  const actions = useFocusKept<HTMLDivElement>();
  const [draft, setDraft] = useState<PercentCrop | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  const brightness = camera.brightness ?? 1;
  const contrast = camera.contrast ?? 1;
  const sharpness = camera.sharpness ?? 0;
  const needsCanvas = brightness !== 1 || contrast !== 1 || sharpness > 0 || rotation !== 0;
  const swap = rotation === 90 || rotation === 270;
  const frameAspect = dims ? (swap ? dims.h / dims.w : dims.w / dims.h) : 16 / 9;
  const watched = toPercent(crop ?? middleSquare(frameAspect));
  const region = editing && draft ? fromPercent(draft) : (crop ?? middleSquare(frameAspect));
  const squares = crop || editing ? scoredSquares(region, frameAspect) : [region];

  useVideoStream(videoRef, camera);

  const measureFrame = ({ currentTarget: video }: SyntheticEvent<HTMLVideoElement>) => {
    if (video.videoWidth === 0) return;
    setDims({ w: video.videoWidth, h: video.videoHeight });
    setDraft(null);
  };

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
        <div ref={actions} className="flex gap-2">
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
              key="edit"
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
            onLoadedMetadata={measureFrame}
            onResize={measureFrame}
            className={`absolute inset-0 w-full h-full object-contain pointer-events-none ${needsCanvas ? "invisible" : ""}`}
          />
          {needsCanvas && <canvas ref={canvasRef} className="absolute inset-0 m-auto pointer-events-none" />}
          {squares.length > 1 &&
            squares.map((square, index) => (
              <span
                key={index}
                aria-hidden
                className="pointer-events-none absolute border border-dashed border-accent/70"
                style={{ left: `${square.x * 100}%`, top: `${square.y * 100}%`, width: `${square.w * 100}%`, height: `${square.h * 100}%` }}
              />
            ))}
        </div>
      </ReactCrop>
      <p role="status" className="text-[0.7rem] leading-snug text-text-2">
        {!crop && !editing
          ? "The model only watches this square until you crop the camera, so frame the print with a crop."
          : squares.length > 1
            ? `The model scores this crop as ${squares.length} overlapping squares, which takes ${squares.length} times the work. Frame it tightly around the print.`
            : "The model watches this crop, so frame it tightly around the print."}
      </p>
    </div>
  );
}
