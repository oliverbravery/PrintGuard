import type { EngineState, PrintFile, Printer } from "./types";

export const ACCEPT = ".gcode,.gco,.g,.bgcode,.3mf";

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

export function formatFilament(print: PrintFile): string | null {
  if (print.meta.filament_g) return `${Math.round(print.meta.filament_g)} g`;
  if (print.meta.filament_mm) return `${(print.meta.filament_mm / 1000).toFixed(1)} m`;
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
  const parts = [print.meta.slicer, print.meta.time_s ? formatDuration(print.meta.time_s) : null, formatFilament(print), print.meta.printer_model];
  return parts.filter((part): part is string => Boolean(part));
}

export function uploadPrint(file: File, printerIds: string[], onProgress: (fraction: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    const params = new URLSearchParams({ filename: file.name, printers: printerIds.join(",") });
    request.open("POST", `api/prints?${params}`);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
    request.onload = () => {
      if (request.status < 400) return resolve();
      let detail = `HTTP ${request.status}`;
      try {
        detail = String(JSON.parse(request.responseText).detail ?? detail);
      } catch {}
      reject(new Error(detail));
    };
    request.onerror = () => reject(new Error("the upload did not reach the hub"));
    request.send(file);
  });
}
