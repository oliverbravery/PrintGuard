export type Mode = "local" | "hub";

export interface Crop {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface CameraSource {
  kind: string;
  device_id?: string;
  path?: string;
  url?: string;
  label?: string;
}

export interface InferenceResult {
  prediction: string;
  distances: Record<string, number>;
  margin: number;
}

export interface Camera {
  id: string;
  name: string;
  source: CameraSource;
  max_fps: number;
  brightness: number;
  contrast: number;
  sharpness: number;
  crop: Crop | null;
  target_fps: number;
  achieved_fps: number;
  inferring: boolean;
  in_use: boolean;
  online: boolean;
  last_result: InferenceResult | null;
}

export interface DeviceState {
  status: string;
  progress: number;
  job: string | null;
}

export interface Printer {
  id: string;
  name: string;
  provider: string;
  config: Record<string, string>;
  device_state?: DeviceState | null;
  online: boolean;
}

export interface Alert {
  score: number;
  action: string;
  ts: number;
}

export interface Monitor {
  id: string;
  name: string;
  camera_id: string;
  printer_id: string;
  enabled: boolean;
  threshold: number;
  sensitivity: number;
  consecutive: number;
  notify: boolean;
  on_defect: "none" | "pause" | "cancel";
  cooldown_s: number;
  alert?: Alert | null;
  watching?: boolean;
}

export interface SchemaProperty {
  type: string;
  title: string;
  format?: string;
  secret?: boolean;
  placeholder?: string;
}

export interface AdapterMeta {
  id: string;
  label: string;
  docs_url: string;
  browser_ok?: boolean;
  experimental?: boolean;
  setup_url?: string | null;
  setup_hint?: string | null;
  schema: {
    properties: Record<string, SchemaProperty>;
    required?: string[];
  };
}

export interface ApiToken {
  id: string;
  name: string;
  scope: "read" | "control" | "manage";
  hint: string;
  created: number;
}

export interface EngineStats {
  workers: number;
  infer_ms: number;
  capacity_fps: number;
}

export interface EngineState {
  mode: string;
  cameras: Camera[];
  printers: Printer[];
  monitors: Monitor[];
  settings: { notifiers: Record<string, Record<string, string>> };
  tokens: ApiToken[];
  stats: EngineStats;
  integrations: AdapterMeta[];
  notifiers: AdapterMeta[];
}

export interface ScorePoint {
  ts: number;
  score: number;
}

export interface EngineLink {
  send(cmd: Record<string, unknown>): void;
  close(): void;
}
