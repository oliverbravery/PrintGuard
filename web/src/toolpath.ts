import type { GCodePreviewOptions, WebGLPreview } from "gcode-preview";
import { log } from "./log";
import type { PrintFile } from "./types";

const PREVIEW_PX = 256;
const PREVIEW_SCALE = 2;
const PREVIEW_INK = 0x9a;

export async function drawToolpath(canvas: HTMLCanvasElement, gcode: string, options: GCodePreviewOptions): Promise<WebGLPreview> {
  const [{ init }, { Box3, Vector3 }] = await Promise.all([import("gcode-preview"), import("three")]);
  const preview = init({ canvas, renderTravel: false, lineWidth: 1.5, ...options });
  preview.processGCode(gcode);
  const bounds = new Box3().setFromObject(preview.scene);
  const centre = bounds.getCenter(new Vector3());
  const reach = bounds.getSize(new Vector3()).length() * 1.3;
  preview.camera.position.set(centre.x + reach * 0.7, centre.y + reach * 0.6, centre.z + reach * 0.7);
  preview.controls.target.copy(centre);
  preview.controls.update();
  return preview;
}

async function renderPreview(gcode: string): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.style.cssText = `position:fixed;left:-9999px;top:0;width:${PREVIEW_PX}px;height:${PREVIEW_PX}px`;
  document.body.append(canvas);
  const preview = await drawToolpath(canvas, gcode, {
    backgroundColor: 0x000000,
    extrusionColor: 0xffffff,
    topLayerColor: 0xffffff,
    lastSegmentColor: 0xffffff,
    disableGradient: true,
    lineWidth: 3,
  });
  try {
    preview.resize();
    preview.renderer.setPixelRatio(PREVIEW_SCALE);
    preview.renderer.setSize(PREVIEW_PX, PREVIEW_PX, false);
    preview.render();
    return await tint(canvas);
  } finally {
    preview.dispose();
    canvas.remove();
  }
}

function tint(source: HTMLCanvasElement): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = PREVIEW_PX;
  const context = canvas.getContext("2d")!;
  context.drawImage(source, 0, 0, PREVIEW_PX, PREVIEW_PX);
  const image = context.getImageData(0, 0, PREVIEW_PX, PREVIEW_PX);
  const pixels = image.data;
  for (let i = 0; i < pixels.length; i += 4) {
    pixels[i + 3] = Math.max(pixels[i], pixels[i + 1], pixels[i + 2]);
    pixels[i] = pixels[i + 1] = pixels[i + 2] = PREVIEW_INK;
  }
  context.putImageData(image, 0, 0);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("the canvas gave no image"))), "image/png"));
}

const drawn = new Set<string>();
let pending: Promise<unknown> = Promise.resolve();

export function drawMissingPreviews(prints: PrintFile[]): void {
  for (const print of prints) {
    if (print.thumbnail || drawn.has(print.id)) continue;
    drawn.add(print.id);
    pending = pending.then(() => storePreview(print)).catch((err: Error) => log("warn", `could not draw a preview for ${print.name}:`, err.message));
  }
}

async function storePreview(print: PrintFile): Promise<void> {
  const gcode = await fetch(`api/prints/${print.id}/gcode`);
  if (gcode.status === 404) return;
  if (!gcode.ok) throw new Error(`HTTP ${gcode.status}`);
  const stored = await fetch(`api/prints/${print.id}/thumbnail`, {
    method: "PUT",
    headers: { "Content-Type": "image/png" },
    body: await renderPreview(await gcode.text()),
  });
  if (!stored.ok) throw new Error(`HTTP ${stored.status}`);
}
