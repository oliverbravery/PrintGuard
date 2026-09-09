import { useEffect, useId, useRef, useState } from "react";
import type { WebGLPreview } from "gcode-preview";
import { formatBytes, formatDuration, formatFilament } from "../prints";
import { useStore } from "../store";
import type { PrintFile } from "../types";
import { Modal } from "./Dialog";
import { SendToPrinter } from "./SendToPrinter";
import { Slider } from "./Slider";

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-3 py-2">
      <div className="mono truncate text-sm text-text-0">{value}</div>
      <div className="label mt-0.5">{label}</div>
    </div>
  );
}

export function PrintViewer({ print }: { print: PrintFile }) {
  const openPrint = useStore((s) => s.openPrint);
  const titleId = useId();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<WebGLPreview | null>(null);
  const [layers, setLayers] = useState(0);
  const [layer, setLayer] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "none" | "failed">("loading");
  const close = () => openPrint(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    let preview: WebGLPreview | null = null;
    const observer = new ResizeObserver(() => preview?.resize());
    (async () => {
      const response = await fetch(`api/prints/${print.id}/gcode`);
      if (disposed) return;
      if (!response.ok) return setStatus(response.status === 404 ? "none" : "failed");
      const text = await response.text();
      if (disposed) return;
      const [{ init }, { Box3, Vector3 }] = await Promise.all([import("gcode-preview"), import("three")]);
      if (disposed) return;
      preview = init({
        canvas,
        backgroundColor: token("--color-ink-0"),
        extrusionColor: token("--color-text-1"),
        topLayerColor: token("--color-accent"),
        lastSegmentColor: token("--color-accent"),
        travelColor: token("--color-line-1"),
        renderTravel: false,
        lineWidth: 1.5,
      });
      previewRef.current = preview;
      preview.processGCode(text);
      const bounds = new Box3().setFromObject(preview.scene);
      const centre = bounds.getCenter(new Vector3());
      const reach = bounds.getSize(new Vector3()).length() * 1.3;
      preview.camera.position.set(centre.x + reach * 0.7, centre.y + reach * 0.6, centre.z + reach * 0.7);
      preview.controls.target.copy(centre);
      preview.controls.update();
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
  }, [print.id]);

  useEffect(() => {
    const preview = previewRef.current;
    if (!preview || status !== "ready") return;
    preview.endLayer = layer;
    preview.render();
  }, [layer, status]);

  const filament = formatFilament(print);
  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in h-full w-full overflow-y-auto border-l border-line-0 bg-ink-1 sm:w-[680px]">
        <div className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-line-0 bg-ink-1/95 px-5 py-3.5 backdrop-blur-sm">
          <h2 id={titleId} className="display flex-1 truncate text-lg font-semibold">
            {print.name}
          </h2>
          <span className="chip">.{print.ext}</span>
          <span className="chip">{formatBytes(print.size)}</span>
          <button type="button" className="cursor-pointer text-2xl leading-none text-text-2 hover:text-accent" onClick={close} aria-label="Close print viewer">
            ×
          </button>
        </div>

        <div className="relative aspect-[4/3] w-full bg-ink-0">
          <canvas ref={canvasRef} className="h-full w-full touch-none" aria-label={`Toolpath of ${print.name}`} />
          {status !== "ready" && (
            <div className="absolute inset-0 grid place-items-center">
              <span className={`mono text-[0.68rem] uppercase tracking-[0.2em] text-text-2 ${status === "loading" ? "boot-cursor" : ""}`}>
                {status === "loading" ? "reading gcode" : status === "none" ? "binary gcode has no toolpath to draw" : "could not draw this file"}
              </span>
            </div>
          )}
        </div>

        <div className="space-y-4 border-b border-line-0 px-5 py-4">
          {status === "ready" && layers > 1 && (
            <Slider label="Layers shown" value={layer} min={1} max={layers} step={1} format={(v) => `${v} / ${layers}`} onChange={setLayer} />
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat label="print time" value={print.meta.time_s ? formatDuration(print.meta.time_s) : "—"} />
            <Stat label="filament" value={filament ?? "—"} />
            <Stat label="sliced for" value={print.meta.printer_model ?? "—"} />
            <Stat label="slicer" value={print.meta.slicer ?? "—"} />
          </div>
        </div>

        <section className="px-5 py-4">
          <h3 className="display mb-3 text-[0.68rem] font-semibold tracking-[0.24em] text-text-2">Send to a printer</h3>
          <SendToPrinter print={print} />
        </section>
      </aside>
    </Modal>
  );
}
