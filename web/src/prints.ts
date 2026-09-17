import type { HeaterName } from "./components/PrinterControls";
import type { EngineState, PrintFile, PrintMeta, Printer } from "./types";

export const FORMATS = ["gcode", "gco", "g", "bgcode", "3mf"];
export const ACCEPT = FORMATS.map((format) => `.${format}`).join(",");
const TEXT_FORMATS = ["gcode", "gco", "g"];
const SAMPLE_HEAD = 4 * 1024 * 1024;
const SAMPLE_TAIL = 512 * 1024;
const PLATE_GCODE = /^Metadata\/plate_(\d+)\.gcode$/;

export type Temperatures = Partial<Record<HeaterName, number>>;

export interface PrintDraft {
  file: File;
  name: string;
  printerIds: string[];
  temperatures: Temperatures;
  drawPreview: boolean;
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
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return h ? `${h}h ${m}m` : `${m}m`;
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

export async function toolpathOf(file: File): Promise<Blob | null> {
  const ext = extOf(file.name);
  if (ext === "bgcode") return null;
  if (ext !== "3mf") return file;
  const { unzipSync } = await import("fflate");
  const archive = new Uint8Array(await file.arrayBuffer());
  const plates: string[] = [];
  unzipSync(archive, {
    filter: ({ name }) => {
      if (PLATE_GCODE.test(name)) plates.push(name);
      return false;
    },
  });
  const [plate] = plates.sort((a, b) => Number(PLATE_GCODE.exec(a)![1]) - Number(PLATE_GCODE.exec(b)![1]));
  if (!plate) throw new Error("this 3mf has not been sliced, export it from Bambu Studio or Orca with the gcode included");
  return new Blob([unzipSync(archive, { filter: ({ name }) => name === plate })[plate] as Uint8Array<ArrayBuffer>]);
}

export async function inspectPrint(file: File, toolpath: Blob | null): Promise<Inspection> {
  const source = toolpath ?? file;
  const sample =
    source.size > SAMPLE_HEAD + SAMPLE_TAIL ? new Blob([source.slice(0, SAMPLE_HEAD), "\n", source.slice(-SAMPLE_TAIL)]) : source;
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
