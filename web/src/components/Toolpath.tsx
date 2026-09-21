import { useEffect, useRef, useState } from "react";
import type { WebGLPreview } from "gcode-preview";
import { drawToolpath } from "../toolpath";
import { Slider } from "./Slider";

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function Toolpath({ label, load }: { label: string; load: () => Promise<string | null> }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<WebGLPreview | null>(null);
  const [layers, setLayers] = useState(0);
  const [layer, setLayer] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "none" | "failed">("loading");

  useEffect(() => {
    const canvas = canvasRef.current!;
    let disposed = false;
    let preview: WebGLPreview | null = null;
    const observer = new ResizeObserver(() => preview?.resize());
    (async () => {
      const gcode = await load();
      if (disposed) return;
      if (gcode === null) return setStatus("none");
      preview = await drawToolpath(canvas, gcode, {
        backgroundColor: token("--color-ink-0"),
        extrusionColor: token("--color-text-1"),
        topLayerColor: token("--color-accent"),
        lastSegmentColor: token("--color-accent"),
        travelColor: token("--color-line-1"),
      });
      if (disposed) return preview.dispose();
      previewRef.current = preview;
      const count = preview.maxLayerIndex + 1;
      setLayers(count);
      setLayer(count);
      setStatus("ready");
      observer.observe(canvas.parentElement!);
    })().catch(() => !disposed && setStatus("failed"));
    return () => {
      disposed = true;
      observer.disconnect();
      previewRef.current?.dispose();
      previewRef.current = null;
    };
  }, []);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview || status !== "ready") return;
    preview.endLayer = layer;
    preview.render();
  }, [layer, status]);

  return (
    <>
      <div className="relative aspect-[4/3] w-full bg-ink-0">
        <canvas ref={canvasRef} className="h-full w-full touch-none" aria-label={`Toolpath of ${label}`} />
        {status !== "ready" && (
          <div className="absolute inset-0 grid place-items-center">
            <span className={`mono text-[0.68rem] uppercase tracking-[0.2em] text-text-2 ${status === "loading" ? "boot-cursor" : ""}`}>
              {status === "loading" ? "reading gcode" : status === "none" ? "binary gcode has no toolpath to draw" : "could not draw this file"}
            </span>
          </div>
        )}
      </div>
      {status === "ready" && layers > 1 && (
        <div className="px-5 pt-4">
          <Slider label="Layers shown" value={layer} min={1} max={layers} step={1} format={(v) => `${v} / ${layers}`} onChange={setLayer} />
        </div>
      )}
    </>
  );
}
