import type { Camera, CameraSource } from "./types";

export function sourceLabel(source: CameraSource): string {
  if (source.kind === "device") return source.label || "device camera";
  if (source.kind === "path") return `path://${source.path}`;
  if (source.kind === "bambu") return `bambu://${source.host ?? ""}`;
  return source.url ? source.url.replace(/\/\/[^?#]*@/, "//") : source.kind;
}

export function cameraStatus(camera: Camera): string {
  if (camera.online) return "online";
  if (camera.standby) return "standby";
  return "offline";
}
