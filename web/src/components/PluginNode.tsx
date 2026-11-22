import { type LucideIcon, Pause, Play, RefreshCw, SkipBack, SkipForward, Square } from "lucide-react";
import { useState, type ReactNode } from "react";
import { floatCamera, floatSupported } from "../float";
import type { BUTTON_ICONS } from "../plugins";
import { useStore } from "../store";
import type { PluginNode as Node, PluginRecord } from "../types";
import { Feed } from "./Feed";
import { Toggle } from "./Toggle";

const TONES: Record<string, string> = { ok: "chip-ok", warn: "chip-warn", bad: "chip-bad", accent: "chip-accent" };

const ICONS: Record<(typeof BUTTON_ICONS)[number], LucideIcon> = {
  play: Play,
  pause: Pause,
  stop: Square,
  previous: SkipBack,
  next: SkipForward,
  refresh: RefreshCw,
};

type Act = (action: string, arg: unknown) => void;

function Labelled({ label, children }: { label?: string; children: ReactNode }) {
  if (!label) return children;
  return (
    <label className="block">
      <span className="label block mb-1">{label}</span>
      {children}
    </label>
  );
}

function PluginInput({ node, act }: { node: Node; act: Act }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null && node.action) act(node.action, node.kind === "number" ? Number(draft) : draft);
    setDraft(null);
  };

  return (
    <Labelled label={node.label}>
      <input
        className="field"
        type={node.secret ? "password" : node.kind === "number" ? "number" : "text"}
        placeholder={node.placeholder}
        value={draft ?? node.value ?? ""}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && commit()}
      />
    </Labelled>
  );
}

export function PluginNodeView({ plugin, node, panel = false }: { plugin: PluginRecord; node: Node; panel?: boolean }) {
  const pluginAct = useStore((s) => s.pluginAct);
  const act = (action: string, arg: unknown) => pluginAct(plugin.id, action, arg, panel);
  return <NodeView node={node} pluginId={plugin.id} mayViewCameras={plugin.granted.includes("camera:view")} act={act} />;
}

export function usePluginSurface(surface: "monitor" | "settings", monitorId: string): { plugin: PluginRecord; node: Node }[] {
  const { engine, pluginViews } = useStore();
  return (engine?.plugins ?? [])
    .filter((plugin) => plugin.enabled && plugin.manifest.surfaces.includes(surface))
    .map((plugin) => ({ plugin, node: pluginViews[plugin.id]?.[`${surface}:${monitorId}`] }))
    .filter((drawn): drawn is { plugin: PluginRecord; node: Node } => drawn.node != null);
}

function NodeView({ node, pluginId, mayViewCameras, act }: { node: Node; pluginId: string; mayViewCameras: boolean; act: Act }) {
  const { engine, pluginAssets, toast } = useStore();

  if (node.type === "row" || node.type === "col") {
    return (
      <div className={node.type === "row" ? "flex flex-wrap items-center gap-2" : "flex flex-col gap-2"}>
        {(node.children ?? []).map((child, index) => (
          <NodeView key={index} node={child} pluginId={pluginId} mayViewCameras={mayViewCameras} act={act} />
        ))}
      </div>
    );
  }

  if (node.type === "text") {
    return <span className={node.muted ? "text-xs text-text-2" : "text-xs text-text-1"}>{node.value}</span>;
  }

  if (node.type === "chip") {
    return <span className={`chip chip-message ${TONES[node.tone ?? ""] ?? ""}`}>{node.value}</span>;
  }

  if (node.type === "camera") {
    if (!mayViewCameras) return <span className="text-xs text-text-2">Camera feeds not permitted</span>;
    const camera = engine?.cameras.find((c) => c.id === node.camera_id);
    return (
      <div className="min-w-[12rem] flex-1 border border-line-0">
        <Feed camera={camera} />
      </div>
    );
  }

  if (node.type === "image") {
    const url = pluginAssets[pluginId]?.[node.asset ?? ""];
    return url ? <img src={url} alt={node.label ?? ""} className="max-h-40 max-w-full border border-line-0" /> : null;
  }

  if (node.type === "float") {
    if (!mayViewCameras || !floatSupported()) return null;
    return (
      <button
        className="chip grid place-items-center min-h-6 min-w-6 cursor-pointer hover:opacity-80"
        aria-label={node.label ?? "Float this camera"}
        onClick={() => floatCamera(node.camera_id ?? "", (reason) => toast("error", `Could not float that camera, ${reason}`))}
      >
        {node.value ?? "⧉"}
      </button>
    );
  }

  if (node.type === "toggle") {
    return (
      <Toggle
        label={node.label ?? "Toggle"}
        on={node.on === true}
        onChange={(on) => node.action && act(node.action, on)}
      />
    );
  }

  if (node.type === "input") return <PluginInput node={node} act={act} />;

  if (node.type === "button") {
    const Icon = node.icon ? ICONS[node.icon as keyof typeof ICONS] : null;
    return (
      <button
        className={Icon ? "btn grid w-9 place-items-center px-0" : "btn"}
        aria-label={Icon ? node.label : undefined}
        title={Icon ? node.label : undefined}
        disabled={node.disabled}
        onClick={() => node.action && act(node.action, node.arg)}
      >
        {Icon ? <Icon size={16} aria-hidden /> : node.label}
      </button>
    );
  }

  return (
    <Labelled label={node.label}>
      <select
        className="field"
        value={String(node.value ?? "")}
        onChange={(event) => node.action && act(node.action, event.target.value)}
      >
        {(node.options ?? []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Labelled>
  );
}
