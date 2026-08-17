import { useStore } from "../store";
import type { PluginNode as Node } from "../types";
import { Feed } from "./Feed";

const TONES: Record<string, string> = { ok: "chip-ok", warn: "chip-warn", bad: "chip-bad", accent: "chip-accent" };

export function PluginNodeView({ node, pluginId, mayViewCameras }: { node: Node; pluginId: string; mayViewCameras: boolean }) {
  const { engine, pluginAct } = useStore();

  if (node.type === "row" || node.type === "col") {
    return (
      <div className={node.type === "row" ? "flex flex-wrap items-center gap-2" : "flex flex-col gap-2"}>
        {(node.children ?? []).map((child, index) => (
          <PluginNodeView key={index} node={child} pluginId={pluginId} mayViewCameras={mayViewCameras} />
        ))}
      </div>
    );
  }

  if (node.type === "text") {
    return <span className={node.muted ? "text-[0.7rem] text-text-2" : "text-xs text-text-1"}>{node.value}</span>;
  }

  if (node.type === "chip") {
    return <span className={`chip ${TONES[node.tone ?? ""] ?? ""}`}>{node.value}</span>;
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

  if (node.type === "button") {
    return (
      <button className="btn" onClick={() => node.action && pluginAct(pluginId, node.action, node.arg)}>
        {node.label}
      </button>
    );
  }

  return (
    <select
      className="field"
      value={String(node.value ?? "")}
      aria-label={node.label}
      onChange={(event) => node.action && pluginAct(pluginId, node.action, event.target.value)}
    >
      {(node.options ?? []).map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
