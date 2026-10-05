import type { HeaterName } from "./components/PrinterControls";
import { tooLargeToDraw, type ToolpathSource } from "./toolpath";
import type { EngineState, PrintFile, PrintMeta, Printer } from "./types";

export const FORMATS = ["gcode", "gco", "g", "bgcode", "3mf"];
export const ACCEPT = [...FORMATS.map((format) => `.${format}`), "application/octet-stream"].join(",");
const TEXT_FORMATS = ["gcode", "gco", "g"];
const SAMPLE_HEAD = 4 * 1024 * 1024;
const SAMPLE_TAIL = 512 * 1024;
const UNZIP_STEP = 64 * 1024;
const PLATE_GCODE = /^Metadata\/plate_(\d+)\.gcode$/;

export type Temperatures = Partial<Record<HeaterName, number>>;

export interface PrintDraft {
  file: File;
  name: string;
  printerIds: string[];
  temperatures: Temperatures;
}

export interface SlicedGcode extends ToolpathSource {
  sample: Blob;
}

export interface Inspection {
  meta: PrintMeta;
  thumbnail: boolean;
}

export function extOf(filename: string): string {
  return filename.includes(".") ? filename.slice(filename.lastIndexOf(".") + 1).toLowerCase() : "";
}

export function printerAccepts(engine: EngineState, printer: Printer, ext: string): boolean {
  return engine.integrations.find((i) => i.id === printer.provider)?.formats?.includes(ext) ?? false;
}

export function acceptedTags(engine: EngineState, printerIds: string[], ext: string): string[] {
  return printerIds.filter((id) => {
    const printer = engine.printers.find((p) => p.id === id);
    return printer !== undefined && printerAccepts(engine, printer, ext);
  });
}

export function eligiblePrinters(engine: EngineState, print: PrintFile): Printer[] {
  return engine.printers.filter(
    (p) => (print.printer_ids.length ? print.printer_ids.includes(p.id) : true) && printerAccepts(engine, p, print.ext),
  );
}

export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return h ? `${h}h ${minutes % 60}m` : `${minutes}m`;
}

export function formatFilament(meta: PrintMeta): string | null {
  if (meta.filament_g) return `${Math.round(meta.filament_g)} g`;
  if (meta.filament_mm) return `${(meta.filament_mm / 1000).toFixed(1)} m`;
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function summary(print: PrintFile): string[] {
  const parts = [print.meta.slicer, print.meta.time_s ? formatDuration(print.meta.time_s) : null, formatFilament(print.meta), print.meta.printer_model];
  return parts.filter((part): part is string => Boolean(part));
}

export function isText(filename: string): boolean {
  return TEXT_FORMATS.includes(extOf(filename));
}

function sampleOf(source: Blob): Blob {
  return source.size > SAMPLE_HEAD + SAMPLE_TAIL ? new Blob([source.slice(0, SAMPLE_HEAD), "\n", source.slice(-SAMPLE_TAIL)]) : source;
}

function drawable(gcode: Blob): SlicedGcode {
  return { size: gcode.size, text: () => gcode.text(), sample: sampleOf(gcode) };
}

class PlateGcode {
  size = 0;
  private head: Uint8Array<ArrayBuffer>[] = [];
  private headRoom = SAMPLE_HEAD;
  private kept: Uint8Array<ArrayBuffer>[] = [];
  private keptSize = 0;

  constructor(readonly plate: number) {}

  take(chunk: Uint8Array<ArrayBuffer>) {
    this.size += chunk.length;
    if (this.headRoom > 0) {
      this.head.push(chunk.subarray(0, this.headRoom));
      this.headRoom -= chunk.length;
    }
    this.kept.push(chunk);
    this.keptSize += chunk.length;
    if (tooLargeToDraw(this)) while (this.keptSize - this.kept[0].length >= SAMPLE_TAIL) this.keptSize -= this.kept.shift()!.length;
  }

  sliced(): SlicedGcode {
    if (!tooLargeToDraw(this)) return drawable(new Blob(this.kept));
    const sample = new Blob([...this.head, "\n", new Blob(this.kept).slice(-SAMPLE_TAIL)]);
    return { size: this.size, text: () => sample.text(), sample };
  }
}

export async function toolpathOf(file: File): Promise<SlicedGcode | null> {
  const ext = extOf(file.name);
  if (ext === "bgcode") return null;
  if (ext !== "3mf") return drawable(file);
  const { Unzip, UnzipInflate } = await import("fflate");
  let first: PlateGcode | undefined;
  const archive = new Unzip((entry) => {
    const plate = Number(PLATE_GCODE.exec(entry.name)?.[1] ?? NaN);
    if (!(plate < (first?.plate ?? Infinity))) return;
    const gcode = (first = new PlateGcode(plate));
    entry.ondata = (error, chunk) => {
      if (error) throw error;
      gcode.take(chunk as Uint8Array<ArrayBuffer>);
    };
    entry.start();
  });
  archive.register(UnzipInflate);
  const reader = file.stream().getReader();
  for (let read = await reader.read(); !read.done; read = await reader.read()) {
    for (let at = 0; at < read.value.length; at += UNZIP_STEP) archive.push(read.value.subarray(at, at + UNZIP_STEP));
  }
  archive.push(new Uint8Array(0), true);
  if (!first) throw new Error("this 3mf has not been sliced, export it from Bambu Studio or Orca with the gcode included");
  return first.sliced();
}

export async function inspectPrint(file: File, toolpath: SlicedGcode | null): Promise<Inspection> {
  const sample = toolpath?.sample ?? sampleOf(file);
  const ext = extOf(file.name) === "3mf" ? "gcode" : extOf(file.name);
  const response = await fetch(`api/prints/inspect?${new URLSearchParams({ ext })}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: sample,
  });
  if (!response.ok) throw new Error(errorDetail(response.status, await response.text()));
  return response.json();
}

function errorDetail(status: number, body: string): string {
  try {
    return String(JSON.parse(body).detail ?? `HTTP ${status}`);
  } catch {
    return `HTTP ${status}`;
  }
}

export function sendPrint(draft: PrintDraft, body: Blob, onProgress: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const params = new URLSearchParams({ filename: draft.file.name, name: draft.name, printer_ids: draft.printerIds.join(",") });
    for (const [heater, target] of Object.entries(draft.temperatures)) params.set(heater, String(target));
    request.open("POST", `api/prints?${params}`);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
    request.onload = () => (request.status < 400 ? resolve() : reject(new Error(errorDetail(request.status, request.responseText))));
    request.onerror = () => reject(new Error("the upload did not reach the hub"));
    request.send(body);
  });
}
