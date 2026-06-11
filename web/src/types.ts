export type Mode = "local" | "hub";

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

export interface DeviceConfig {
  provider: string | null;
  config: Record<string, string>;
  on_defect: "none" | "pause" | "cancel";
  cooldown_s: number;
}

export interface Alert {
  score: number;
  action: string;
  ts: number;
}

export interface Printer {
  id: string;
  name: string;
  camera_id: string;
  enabled: boolean;
  threshold: number;
  sensitivity: number;
  consecutive: number;
  notify: boolean;
  device: DeviceConfig;
  device_state?: DeviceState;
  alert?: Alert | null;
}

export interface SchemaProperty {
  type: string;
  title: string;
  format?: string;
  secret?: boolean;
  placeholder?: string;
}

export interface IntegrationMeta {
  id: string;
  label: string;
  docs_url: string;
  schema: {
    properties: Record<string, SchemaProperty>;
    required?: string[];
  };
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
  settings: { ntfy_url: string; whep_base: string };
  stats: EngineStats;
  integrations: IntegrationMeta[];
}

export interface ScorePoint {
  ts: number;
  score: number;
}

export interface EngineLink {
  send(cmd: Record<string, unknown>): void;
  close(): void;
}
