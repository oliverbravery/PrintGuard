import { useEffect, useRef, useState } from "react";
import type { WebGLPreview } from "gcode-preview";
import { drawToolpath, releaseToolpath, tooLargeToDraw, TOOLPATH_MAX_MB, type ParsedToolpath, type ToolpathSource } from "../toolpath";
import { Slider } from "./Slider";

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

type Status = "loading" | "ready" | "none" | "large" | "failed";

const UNDRAWN: Record<Exclude<Status, "ready">, string> = {
  loading: "reading gcode",
  none: "binary gcode has no toolpath to draw",
  large: `files over ${TOOLPATH_MAX_MB} MB are not drawn`,
  failed: "could not draw this file",
};

export function Toolpath({
  label,
  load,
  onSettled,
}: {
  label: string;
  load: () => Promise<ToolpathSource | null>;
  onSettled?: (parsed: ParsedToolpath | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<WebGLPreview | null>(null);
  const [layers, setLayers] = useState(0);
  const [layer, setLayer] = useState(0);
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    const canvas = canvasRef.current!;
    let disposed = false;
    let preview: WebGLPreview | null = null;
    const observer = new ResizeObserver(() => preview?.resize());
    const settle = (outcome: Status, parsed: ParsedToolpath | null = null) => {
      if (disposed) return;
      setStatus(outcome);
      onSettled?.(parsed);
    };
    (async () => {
      const source = await load();
      if (disposed) return;
      if (source === null) return settle("none");
      if (tooLargeToDraw(source)) return settle("large");
      preview = await drawToolpath(canvas, await source.text(), {
        backgroundColor: token("--color-ink-0"),
        extrusionColor: token("--color-text-1"),
        topLayerColor: token("--color-accent"),
        lastSegmentColor: token("--color-accent"),
        travelColor: token("--color-line-1"),
      });
      if (disposed) return releaseToolpath(preview);
      previewRef.current = preview;
      const count = preview.maxLayerIndex + 1;
      setLayers(count);
      setLayer(count);
      settle("ready", preview.parser);
      observer.observe(canvas.parentElement!);
    })().catch(() => settle("failed"));
    return () => {
      disposed = true;
      observer.disconnect();
      if (previewRef.current) releaseToolpath(previewRef.current);
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
              {UNDRAWN[status]}
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
