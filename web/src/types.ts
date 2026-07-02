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
  host?: string;
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
  printer_id?: string | null;
  max_fps: number;
  brightness: number;
  contrast: number;
  sharpness: number;
  crop: Crop | null;
  rotation: number;
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

export interface HistoryBucket {
  t: number;
  n: number;
  sum: number;
  min: number;
  max: number;
  defects: number;
}

export interface Snapshot {
  id: string;
  ts: number;
  score: number;
  action: string;
}

export interface HistoryAlert {
  ts: number;
  score: number;
  action: string;
}

export interface HistoryStats {
  current: number;
  avg: number;
  min: number;
  max: number;
  inferences: number;
  defect_frames: number;
  defect_pct: number;
  alerts: number;
  watch_min: number;
  snaps: number;
}

export interface MonitorHistory {
  buckets: HistoryBucket[];
  snaps: Snapshot[];
  alerts: HistoryAlert[];
  stats: Partial<HistoryStats>;
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

export interface MqttConfig {
  enabled?: boolean;
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  tls?: boolean;
  base_topic?: string;
  discovery_prefix?: string;
}

export interface ApiToken {
  id: string;
  name: string;
  scope: "read" | "control" | "manage";
  hint: string;
  created: number;
}

export type ThemeBase = "dark" | "light";

export type ThemeTokenKey =
  | "ink0" | "ink1" | "ink2" | "ink3"
  | "line0" | "line1"
  | "text0" | "text1" | "text2"
  | "accent" | "ok" | "warn" | "bad";

export interface CustomTheme {
  id: string;
  name: string;
  base: ThemeBase;
  colors: Record<ThemeTokenKey, string>;
}

export interface LayoutSection {
  order: string[];
  pinned: string[];
  hidden: string[];
}

export interface Layout {
  monitors: LayoutSection;
  cameras: LayoutSection;
}

export interface EngineStats {
  workers: number;
  infer_ms: number;
  capacity_fps: number;
}

export interface UpdateRelease {
  version: string;
  name: string;
  notes: string;
  url: string;
  published_at: string | null;
}

export interface UpdateInfo {
  current: string;
  latest: string;
  available: boolean;
  releases: UpdateRelease[];
  checked_at: number;
  releases_url: string;
}

export interface EngineState {
  mode: string;
  version: string;
  update: UpdateInfo | null;
  cameras: Camera[];
  printers: Printer[];
  monitors: Monitor[];
  settings: {
    notifiers: Record<string, Record<string, string>>;
    update_check: boolean;
    mqtt?: MqttConfig;
    theme: string;
    themes: CustomTheme[];
    layout?: Layout;
  };
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
