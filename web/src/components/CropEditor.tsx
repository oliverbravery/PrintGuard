import { useState } from "react";
import ReactCrop, { type PercentCrop } from "react-image-crop";
import { useFocusKept } from "../a11y";
import type { Camera, Crop } from "../types";
import { Feed } from "./Feed";

const MIN_SIZE_PX = 32;
const LONGEST_RATIO = 4;
const SQUARE_OVERLAP = 0.2;

const WHOLE_FRAME: Crop = { x: 0, y: 0, w: 1, h: 1 };

function squareIn(region: Crop, aspect: number): Crop {
  const w = Math.min(region.w, region.h / aspect);
  const h = w * aspect;
  return { x: region.x + (region.w - w) / 2, y: region.y + (region.h - h) / 2, w, h };
}

function isSquare(region: Crop, aspect: number): boolean {
  return Math.abs(region.w * aspect - region.h) <= 0.01 * region.h;
}

function squareStarts(long: number, short: number): number[] {
  const span = Math.min(long, short * LONGEST_RATIO);
  const ratio = span / short;
  if (ratio <= 1 + SQUARE_OVERLAP) return [(long - short) / 2];
  const count = Math.ceil((ratio - SQUARE_OVERLAP) / (1 - SQUARE_OVERLAP));
  const step = (span - short) / (count - 1);
  return Array.from({ length: count }, (_, index) => (long - span) / 2 + index * step);
}

function scoredSquares(crop: Crop, aspect: number): Crop[] {
  const width = crop.w * aspect;
  if (width >= crop.h) return squareStarts(width, crop.h).map((start) => ({ x: crop.x + start / aspect, y: crop.y, w: crop.h / aspect, h: crop.h }));
  return squareStarts(crop.h, width).map((start) => ({ x: crop.x, y: crop.y + start, w: crop.w, h: width }));
}

export interface FrameSize {
  w: number;
  h: number;
}

export function frameAspect(frame: FrameSize | null, rotation: number): number {
  const { w, h } = frame ?? { w: 16, h: 9 };
  return rotation === 90 || rotation === 270 ? h / w : w / h;
}

export function turnedCrop(crop: Crop, aspectBeforeTurn: number): Crop {
  const w = crop.w * aspectBeforeTurn;
  const h = crop.h / aspectBeforeTurn;
  const fit = Math.min(1, 1 / w, 1 / h);
  const within = (start: number, size: number) => Math.min(Math.max(start, 0), 1 - size);
  return { x: within(crop.x + (crop.w - w * fit) / 2, w * fit), y: within(crop.y + (crop.h - h * fit) / 2, h * fit), w: w * fit, h: h * fit };
}

function toPercent(crop: Crop): PercentCrop {
  return { unit: "%", x: crop.x * 100, y: crop.y * 100, width: crop.w * 100, height: crop.h * 100 };
}

function fromPercent(crop: PercentCrop): Crop {
  return { x: crop.x / 100, y: crop.y / 100, w: crop.width / 100, h: crop.height / 100 };
}

export function CropEditor({
  camera,
  active,
  frame,
  onFrame,
  onChange,
}: {
  camera: Camera;
  active: boolean;
  frame: FrameSize | null;
  onFrame: (frame: FrameSize) => void;
  onChange: (crop: Crop | null) => void;
}) {
  const crop = camera.crop ?? null;
  const [editing, setEditing] = useState(false);
  const controls = useFocusKept<HTMLDivElement>();
  const [draft, setDraft] = useState<PercentCrop | null>(null);
  const [freeform, setFreeform] = useState(false);
  const aspect = frameAspect(frame, camera.rotation);
  const watched = toPercent(crop ?? squareIn(WHOLE_FRAME, aspect));
  const region = editing && draft ? fromPercent(draft) : (crop ?? squareIn(WHOLE_FRAME, aspect));
  const squares = crop || editing ? scoredSquares(region, aspect) : [region];

  const measureFrame = (size: FrameSize) => {
    onFrame(size);
    setDraft(null);
  };

  return (
    <div ref={controls}>
      <div className="relative grid aspect-video place-items-center bg-ink-1 [container-type:size]">
        <ReactCrop
          className={`ReactCrop--no-animate select-none ${editing ? "touch-none" : ""}`}
          style={{ display: "block", width: `min(100cqw, ${aspect * 100}cqh)` }}
          crop={editing && draft ? draft : watched}
          aspect={freeform ? undefined : 1}
          minWidth={MIN_SIZE_PX}
          keepSelection
          disabled={!editing}
          onChange={(_, percent) => setDraft(percent)}
          onComplete={(_, percent) => onChange(fromPercent(percent))}
        >
          <Feed camera={camera} active={active} aspect={aspect} uncropped onFrameSize={measureFrame}>
            {squares.length > 1 &&
              squares.map((square, index) => (
                <span
                  key={index}
                  aria-hidden
                  className="pointer-events-none absolute border border-dashed border-accent/70"
                  style={{ left: `${square.x * 100}%`, top: `${square.y * 100}%`, width: `${square.w * 100}%`, height: `${square.h * 100}%` }}
                />
              ))}
          </Feed>
        </ReactCrop>
        {!editing && (
          <button
            className="btn absolute top-3 right-3 z-[5]"
            onClick={() => {
              setDraft(watched);
              setFreeform(!isSquare(fromPercent(watched), aspect));
              setEditing(true);
            }}
          >
            {crop ? "Edit crop" : "Set crop"}
          </button>
        )}
      </div>
      {editing && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line-0 px-4 py-2">
          <div role="group" aria-label="Crop shape" className="flex flex-1 gap-1">
            {[false, true].map((shape) => (
              <button
                key={String(shape)}
                className="btn-inline"
                aria-pressed={freeform === shape}
                onClick={() => {
                  setFreeform(shape);
                  if (shape) return;
                  const square = squareIn(region, aspect);
                  setDraft(toPercent(square));
                  onChange(square);
                }}
              >
                {shape ? "Freeform" : "Square"}
              </button>
            ))}
          </div>
          <button
            className="btn-inline"
            onClick={() => {
              onChange(null);
              setEditing(false);
            }}
          >
            Reset
          </button>
          <button className="btn-inline btn-inline-accent" onClick={() => setEditing(false)}>
            Done
          </button>
        </div>
      )}
      {editing && freeform && (
        <p role="status" className="border-t border-line-0 px-4 py-2 text-xs leading-snug text-warn">
          Square crops tend to do better at spotting defects than wide ones. A freeform crop still works, but detection might be worse.
        </p>
      )}
      <p role="status" className="border-t border-line-0 px-4 py-2 text-xs leading-snug text-text-2">
        {!crop && !editing
          ? "The model only watches this square until you crop the camera, so frame the print with a crop."
          : squares.length > 1
            ? `The model scores this crop as ${squares.length} overlapping squares, which takes ${squares.length} times the work. Frame it tightly around the print.`
            : "The model watches this crop, so frame it tightly around the print."}
      </p>
    </div>
  );
}
