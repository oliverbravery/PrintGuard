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
  standby: boolean;
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
  result?: ScorePoint | null;
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
  now: number;
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
  enum?: string[];
  enum_labels?: string[];
  default?: string;
}

export interface AdapterMeta {
  id: string;
  label: string;
  docs_url: string;
  browser_ok?: boolean;
  desktop_only?: boolean;
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

export interface Glass {
  opacity: number;
  tone: number;
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

export interface Permission {
  id: string;
  label: string;
  description: string;
  risky?: boolean;
  hub_only?: boolean;
  urls?: boolean;
  channels?: boolean;
  commands?: string[];
  fields?: Record<string, string[]>;
}

export interface PluginManifest {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  homepage: string;
  icon?: string;
  media?: string[];
  permissions: string[];
  reasons: Record<string, string>;
  surfaces: ("panel" | "monitor" | "settings")[];
  platforms: string[];
  urls: string[];
  secrets: Record<string, string>;
  provides: Record<string, string>;
  consumes: string[];
  oauth: { authorize_url: string; token_url: string; register_url: string; scopes: string[]; label: string } | Record<string, never>;
  events: string[];
  tick_s: number;
}

export interface PluginRecord {
  id: string;
  manifest: PluginManifest;
  files: string[];
  digests: Record<string, string>;
  source: { kind: string; repo?: string; path?: string; ref?: string; filename?: string };
  granted: string[];
  config: Record<string, unknown>;
  secrets_set: string[];
  verified: boolean;
  enabled: boolean;
  installed: number;
  failure: string | null;
}

export interface CatalogueEntry {
  id: string;
  name: string;
  description?: string;
  author?: string;
  icon?: string;
  media?: string[];
  repo: string;
  path?: string;
  ref: string;
  version?: string;
  permissions?: string[];
  surfaces?: string[];
  platforms?: string[];
  digests: Record<string, string>;
}

export interface PluginNode {
  type: string;
  value?: string;
  label?: string;
  tone?: string;
  muted?: boolean;
  camera_id?: string;
  asset?: string;
  secret?: boolean;
  kind?: string;
  placeholder?: string;
  on?: boolean;
  action?: string;
  arg?: unknown;
  options?: { value: string; label: string }[];
  children?: PluginNode[];
}

export interface PluginTone {
  hz: number;
  ms: number;
  shape?: string;
  together?: boolean;
}

export interface PluginEffect {
  image?: string;
  action?: string;
  kind: string;
  cmd?: Record<string, unknown>;
  request?: Record<string, unknown>;
  text?: string;
  tones?: PluginTone[];
  asset?: string;
}

export interface EngineStats {
  inference_device: string;
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
  download: string | null;
  checked_at: number;
  releases_url: string;
}

export interface EngineState {
  mode: string;
  host: string;
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
    glass: Glass;
    layout?: Layout;
    inference_runtime: "auto" | "litert" | "onnx";
    catalogue_url: string;
  };
  tokens: ApiToken[];
  stats: EngineStats;
  integrations: AdapterMeta[];
  notifiers: AdapterMeta[];
  plugins: PluginRecord[];
  plugin_permissions: Permission[];
  plugin_events: Record<string, string[]>;
  plugin_event_permissions: Record<string, string>;
  plugin_oauth_callback: string;
  plugin_platforms: Record<string, string>;
  plugin_assets: Record<string, string>;
  plugin_host: boolean;
}

export interface ScorePoint {
  ts: number;
  score: number;
}

export interface EngineLink {
  send(cmd: Record<string, unknown>): void;
  close(): void;
}
