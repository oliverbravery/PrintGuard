import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { PluginNodeView } from "./PluginNode";

export function PluginPanel({ plugin }: { plugin: PluginRecord }) {
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const mayViewCameras = plugin.granted.includes("camera:view");

  const body = tree ? (
    <PluginNodeView node={tree} pluginId={plugin.id} mayViewCameras={mayViewCameras} />
  ) : (
    <span className="text-[0.7rem] text-text-2">{failure ?? "Starting"}</span>
  );

  return (
    <section className="panel p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="display text-sm font-semibold tracking-[0.08em] truncate flex-1">{plugin.manifest.name}</h3>
        <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
      </div>
      {body}
    </section>
  );
}

export function PluginSection() {
  const plugins = useStore((s) => s.engine?.plugins ?? []);
  const panels = plugins.filter((p) => p.enabled && p.files.includes("plugin.js") && p.manifest.surfaces.includes("panel"));
  if (panels.length === 0) return null;
  return (
    <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr))]">
      {panels.map((plugin) => (
        <PluginPanel key={plugin.id} plugin={plugin} />
      ))}
    </div>
  );
}
