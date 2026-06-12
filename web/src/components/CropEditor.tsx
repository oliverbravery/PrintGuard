import { useCallback, useEffect, useRef, useState } from "react";
import { renderVideoFrame, useVideoStream } from "../image";
import type { Camera, Crop } from "../types";

const MIN_SIZE = 0.05;

type Handle = "move" | "tl" | "tr" | "bl" | "br" | "t" | "b" | "l" | "r";

const HANDLES: Array<{ key: Exclude<Handle, "move">; style: React.CSSProperties; cursor: string }> = [
  { key: "tl", style: { top: -5, left: -5 }, cursor: "nwse-resize" },
  { key: "tr", style: { top: -5, right: -5 }, cursor: "nesw-resize" },
  { key: "bl", style: { bottom: -5, left: -5 }, cursor: "nesw-resize" },
  { key: "br", style: { bottom: -5, right: -5 }, cursor: "nwse-resize" },
  { key: "t", style: { top: -3, left: "20%", right: "20%", height: 6 }, cursor: "ns-resize" },
  { key: "b", style: { bottom: -3, left: "20%", right: "20%", height: 6 }, cursor: "ns-resize" },
  { key: "l", style: { left: -3, top: "20%", bottom: "20%", width: 6 }, cursor: "ew-resize" },
  { key: "r", style: { right: -3, top: "20%", bottom: "20%", width: 6 }, cursor: "ew-resize" },
];

function clampCrop(c: Crop): Crop {
  const x = Math.max(0, Math.min(1 - MIN_SIZE, c.x));
  const y = Math.max(0, Math.min(1 - MIN_SIZE, c.y));
  const w = Math.max(MIN_SIZE, Math.min(1 - x, c.w));
  const h = Math.max(MIN_SIZE, Math.min(1 - y, c.h));
  return { x, y, w, h };
}

export function CropEditor({
  camera,
  mode,
  crop,
  onChange,
}: {
  camera: Camera;
  mode: string;
  crop: Crop | null;
  onChange: (crop: Crop | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Crop>(crop ?? { x: 0, y: 0, w: 1, h: 1 });
  const dragRef = useRef<{ handle: Handle; startX: number; startY: number; startCrop: Crop } | null>(null);

  const brightness = camera.brightness ?? 1;
  const contrast = camera.contrast ?? 1;
  const sharpness = camera.sharpness ?? 0;
  const needsCanvas = brightness !== 1 || contrast !== 1 || sharpness > 0;

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
        renderVideoFrame(ctx, video, canvas, { brightness, contrast, sharpness });
      }
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [camera.id, needsCanvas, brightness, contrast, sharpness]);

  useEffect(() => {
    if (!editing) setDraft(crop ?? { x: 0, y: 0, w: 1, h: 1 });
  }, [crop, editing]);

  const toNormalised = useCallback((clientX: number, clientY: number): [number, number] => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return [0, 0];
    return [(clientX - rect.left) / rect.width, (clientY - rect.top) / rect.height];
  }, []);

  const onPointerDown = useCallback(
    (handle: Handle) => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const [nx, ny] = toNormalised(e.clientX, e.clientY);
      dragRef.current = { handle, startX: nx, startY: ny, startCrop: { ...draft } };
    },
    [draft, toNormalised],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragRef.current) return;
      const [nx, ny] = toNormalised(e.clientX, e.clientY);
      const dx = nx - dragRef.current.startX;
      const dy = ny - dragRef.current.startY;
      const s = dragRef.current.startCrop;
      let next = { ...s };

      switch (dragRef.current.handle) {
        case "move":
          next = { x: s.x + dx, y: s.y + dy, w: s.w, h: s.h };
          break;
        case "tl":
          next = { x: s.x + dx, y: s.y + dy, w: s.w - dx, h: s.h - dy };
          break;
        case "tr":
          next = { x: s.x, y: s.y + dy, w: s.w + dx, h: s.h - dy };
          break;
        case "bl":
          next = { x: s.x + dx, y: s.y, w: s.w - dx, h: s.h + dy };
          break;
        case "br":
          next = { x: s.x, y: s.y, w: s.w + dx, h: s.h + dy };
          break;
        case "t":
          next = { x: s.x, y: s.y + dy, w: s.w, h: s.h - dy };
          break;
        case "b":
          next = { x: s.x, y: s.y, w: s.w, h: s.h + dy };
          break;
        case "l":
          next = { x: s.x + dx, y: s.y, w: s.w - dx, h: s.h };
          break;
        case "r":
          next = { x: s.x, y: s.y, w: s.w + dx, h: s.h };
          break;
      }
      setDraft(clampCrop(next));
    },
    [toNormalised],
  );

  const onPointerUp = useCallback(() => {
    if (!dragRef.current) return;
    dragRef.current = null;
    const c = draft;
    if (c.x === 0 && c.y === 0 && c.w === 1 && c.h === 1) {
      onChange(null);
    } else {
      onChange(c);
    }
  }, [draft, onChange]);

  const displayCrop = editing ? draft : (crop ?? { x: 0, y: 0, w: 1, h: 1 });
  const isFullFrame = !crop;

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
                  setDraft({ x: 0, y: 0, w: 1, h: 1 });
                  onChange(null);
                  setEditing(false);
                }}
              >
                Reset
              </button>
              <button
                className="btn btn-primary !py-1 !px-2.5 !text-[0.62rem]"
                onClick={() => {
                  const c = draft;
                  onChange(c.x === 0 && c.y === 0 && c.w === 1 && c.h === 1 ? null : c);
                  setEditing(false);
                }}
              >
                Done
              </button>
            </>
          ) : (
            <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setEditing(true)}>
              {isFullFrame ? "Set crop" : "Edit crop"}
            </button>
          )}
        </div>
      </div>
      <div
        ref={containerRef}
        className="relative bg-ink-0 overflow-hidden select-none touch-none"
        style={{ aspectRatio: "16 / 9" }}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <video ref={videoRef} autoPlay muted playsInline className={`absolute inset-0 w-full h-full object-contain pointer-events-none ${needsCanvas ? "invisible" : ""}`} />
        {needsCanvas && <canvas ref={canvasRef} className="absolute inset-0 m-auto pointer-events-none" />}
        {editing && (
          <>
            <div
              className="absolute border-2 border-accent"
              style={{
                left: `${displayCrop.x * 100}%`,
                top: `${displayCrop.y * 100}%`,
                width: `${displayCrop.w * 100}%`,
                height: `${displayCrop.h * 100}%`,
                cursor: "move",
              }}
              onPointerDown={onPointerDown("move")}
            >
              {HANDLES.map(({ key, style, cursor }) => (
                <div
                  key={key}
                  className={`absolute ${style.width || style.height ? "bg-accent/50" : "w-3 h-3 bg-accent border border-ink-0"}`}
                  style={{ ...style, cursor }}
                  onPointerDown={onPointerDown(key)}
                />
              ))}
            </div>
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background: `
                  linear-gradient(to right, rgba(0,0,0,0.5) ${displayCrop.x * 100}%, transparent ${displayCrop.x * 100}%, transparent ${(displayCrop.x + displayCrop.w) * 100}%, rgba(0,0,0,0.5) ${(displayCrop.x + displayCrop.w) * 100}%),
                  linear-gradient(to bottom, rgba(0,0,0,0.5) ${displayCrop.y * 100}%, transparent ${displayCrop.y * 100}%, transparent ${(displayCrop.y + displayCrop.h) * 100}%, rgba(0,0,0,0.5) ${(displayCrop.y + displayCrop.h) * 100}%)
                `,
              }}
            />
          </>
        )}
        {!editing && !isFullFrame && (
          <div
            className="absolute border border-accent/60 pointer-events-none"
            style={{
              left: `${displayCrop.x * 100}%`,
              top: `${displayCrop.y * 100}%`,
              width: `${displayCrop.w * 100}%`,
              height: `${displayCrop.h * 100}%`,
            }}
          />
        )}
      </div>
      {!editing && !isFullFrame && (
        <p className="mono text-[0.62rem] text-text-2">
          {(displayCrop.w * 100).toFixed(0)}% × {(displayCrop.h * 100).toFixed(0)}% at ({(displayCrop.x * 100).toFixed(0)}%, {(displayCrop.y * 100).toFixed(0)}%)
        </p>
      )}
    </div>
  );
}
