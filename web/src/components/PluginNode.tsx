import { useState, type ReactNode } from "react";
import { floatCamera, floatSupported } from "../float";
import { useStore } from "../store";
import type { PluginNode as Node, PluginRecord } from "../types";
import { Feed } from "./Feed";
import { Toggle } from "./Toggle";

const TONES: Record<string, string> = { ok: "chip-ok", warn: "chip-warn", bad: "chip-bad", accent: "chip-accent" };

function Labelled({ label, children }: { label?: string; children: ReactNode }) {
  if (!label) return children;
  return (
    <label className="block">
      <span className="label block mb-1">{label}</span>
      {children}
    </label>
  );
}

function PluginInput({ node, pluginId }: { node: Node; pluginId: string }) {
  const pluginAct = useStore((s) => s.pluginAct);
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null && node.action) pluginAct(pluginId, node.action, node.kind === "number" ? Number(draft) : draft);
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

export function PluginNodeView({ plugin, node }: { plugin: PluginRecord; node: Node }) {
  return <NodeView node={node} pluginId={plugin.id} mayViewCameras={plugin.granted.includes("camera:view")} />;
}

export function usePluginSurface(surface: "monitor" | "settings", monitorId: string): { plugin: PluginRecord; node: Node }[] {
  const { engine, pluginViews } = useStore();
  return (engine?.plugins ?? [])
    .filter((plugin) => plugin.enabled && plugin.manifest.surfaces.includes(surface))
    .map((plugin) => ({ plugin, node: pluginViews[plugin.id]?.[`${surface}:${monitorId}`] }))
    .filter((drawn): drawn is { plugin: PluginRecord; node: Node } => drawn.node != null);
}

function NodeView({ node, pluginId, mayViewCameras }: { node: Node; pluginId: string; mayViewCameras: boolean }) {
  const { engine, pluginAct, pluginAssets, toast } = useStore();

  if (node.type === "row" || node.type === "col") {
    return (
      <div className={node.type === "row" ? "flex flex-wrap items-center gap-2" : "flex flex-col gap-2"}>
        {(node.children ?? []).map((child, index) => (
          <NodeView key={index} node={child} pluginId={pluginId} mayViewCameras={mayViewCameras} />
        ))}
      </div>
    );
  }

  if (node.type === "text") {
    return <span className={node.muted ? "text-[0.7rem] text-text-2" : "text-xs text-text-1"}>{node.value}</span>;
  }

  if (node.type === "chip") {
    return <span className={`chip chip-message ${TONES[node.tone ?? ""] ?? ""}`}>{node.value}</span>;
  }

  if (node.type === "camera") {
    if (!mayViewCameras) return <span className="text-[0.7rem] text-text-2">Camera feeds not permitted</span>;
    const camera = engine?.cameras.find((c) => c.id === node.camera_id);
    return (
      <div className="min-w-[12rem] flex-1 border border-line-0">
        <Feed camera={camera} mode={engine?.mode ?? "hub"} />
      </div>
    );
  }

  if (node.type === "image") {
    const url = pluginAssets[pluginId]?.[node.asset ?? ""];
    return url ? <img src={url} alt={node.label ?? ""} className="max-h-40 max-w-full rounded border border-line-0" /> : null;
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
        onChange={(on) => node.action && pluginAct(pluginId, node.action, on)}
      />
    );
  }

  if (node.type === "input") return <PluginInput node={node} pluginId={pluginId} />;

  if (node.type === "button") {
    return (
      <button className="btn" onClick={() => node.action && pluginAct(pluginId, node.action, node.arg)}>
        {node.label}
      </button>
    );
  }

  return (
    <Labelled label={node.label}>
      <select
        className="field"
        value={String(node.value ?? "")}
        onChange={(event) => node.action && pluginAct(pluginId, node.action, event.target.value)}
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
