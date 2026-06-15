import { cameraApi, listVideoInputs } from "./media";
import type { EngineLink } from "./types";

const PYODIDE_BASE = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
const LITERT_MODULE = "https://esm.sh/@litertjs/core@2.4.0";
const LITERT_WASM = "https://cdn.jsdelivr.net/npm/@litertjs/core@2.4.0/wasm/";
const MODEL_URL = "models/encoder_float32.tflite";
const STORAGE_KEY = "pg.local.state";

interface OpenCamera {
  stream: MediaStream;
  video: HTMLVideoElement;
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
}

const cameras = new Map<string, OpenCamera>();
let litert: { run: (input: Float32Array) => Promise<Float32Array> } | null = null;

async function ensureLitert() {
  if (litert) return litert;
  const mod = await import(/* @vite-ignore */ LITERT_MODULE);
  await mod.loadLiteRt(LITERT_WASM, { threads: false, jspi: false });
  const model = await mod.loadAndCompile(MODEL_URL, { accelerator: "wasm" });
  litert = {
    async run(input: Float32Array) {
      const tensor = new mod.Tensor(input, [1, 3, 224, 224]);
      const outputs = await model.run([tensor]);
      const data = await outputs[0].data();
      tensor.delete();
      for (const out of outputs) out.delete();
      return new Float32Array(data);
    },
  };
  return litert;
}

export const bridge = {
  async discover() {
    const devices = await listVideoInputs();
    return devices.map((d, i) => ({ kind: "device", device_id: d.deviceId, label: d.label || `Camera ${i + 1}` }));
  },

  async openCamera(cameraId: string, deviceId: string): Promise<number> {
    bridge.closeCamera(cameraId);
    const stream = await cameraApi().getUserMedia({
      video: { deviceId: { exact: deviceId } },
      audio: false,
    });
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    cameras.set(cameraId, { stream, video, canvas, ctx });
    return stream.getVideoTracks()[0]?.getSettings().frameRate ?? 0;
  },

  isLive(cameraId: string): boolean {
    const cam = cameras.get(cameraId);
    return cam?.stream.getVideoTracks()[0]?.readyState === "live";
  },

  grab(cameraId: string) {
    const cam = cameras.get(cameraId);
    if (!cam || cam.video.readyState < 2 || !cam.video.videoWidth) return null;
    const { video, canvas, ctx } = cam;
    if (canvas.width !== video.videoWidth) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
    }
    ctx.drawImage(video, 0, 0);
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height) as ImageData & { seq: number };
    image.seq = video.currentTime;
    return image;
  },

  closeCamera(cameraId: string) {
    const cam = cameras.get(cameraId);
    if (!cam) return;
    cam.stream.getTracks().forEach((t) => t.stop());
    cam.video.srcObject = null;
    cameras.delete(cameraId);
  },

  getStream(cameraId: string): MediaStream | null {
    return cameras.get(cameraId)?.stream ?? null;
  },

  async infer(bytes: Uint8Array): Promise<Float32Array> {
    const rt = await ensureLitert();
    const input = new Float32Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    return rt.run(input);
  },

  async jpegFromRgba(bytes: Uint8Array, width: number, height: number): Promise<ArrayBuffer | null> {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d")!;
    ctx.putImageData(new ImageData(new Uint8ClampedArray(bytes), width, height), 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
    return blob ? blob.arrayBuffer() : null;
  },

  storageLoad(): string {
    return localStorage.getItem(STORAGE_KEY) ?? "";
  },

  storageSave(state: string) {
    localStorage.setItem(STORAGE_KEY, state);
  },
};

declare global {
  interface Window {
    __pg: typeof bridge;
    loadPyodide: (opts: { indexURL: string }) => Promise<any>;
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(script);
  });
}

export async function bootLocal(
  onEvent: (event: any) => void,
  onProgress: (message: string) => void,
): Promise<EngineLink> {
  window.__pg = bridge;
  onProgress("Loading Python runtime");
  await loadScript(`${PYODIDE_BASE}pyodide.js`);
  const pyodide = await window.loadPyodide({ indexURL: PYODIDE_BASE });
  onProgress("Loading numpy");
  await pyodide.loadPackage("numpy");
  onProgress("Fetching engine source");
  const archive = await (await fetch("pysrc.zip")).arrayBuffer();
  pyodide.unpackArchive(archive, "zip");
  onProgress("Compiling model runtime");
  await ensureLitert();
  onProgress("Starting engine");
  pyodide.globals.set("__pg_sink", (payload: string) => onEvent(JSON.parse(payload)));
  await pyodide.runPythonAsync("from printguard.browser import boot\nawait boot.start(__pg_sink)");
  const handle = pyodide.runPython("boot.handle");
  return {
    send: (cmd) => handle(JSON.stringify(cmd)),
    close: () => {},
  };
}
