import { floatSupported } from "../float";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { PluginNodeView } from "./PluginNode";

export function PluginPanel({ plugin }: { plugin: PluginRecord }) {
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const popped = useStore((s) => s.poppedPlugin === plugin.id);
  const popPlugin = useStore((s) => s.popPlugin);
  const floatable = plugin.manifest.surfaces.includes("float") && floatSupported();
  const mayViewCameras = plugin.granted.includes("camera:view");

  const needsPermissions = plugin.granted.length === 0 && plugin.manifest.permissions.length > 0;
  const body = tree ? (
    <PluginNodeView node={tree} pluginId={plugin.id} mayViewCameras={mayViewCameras} />
  ) : (
    <span className="text-[0.7rem] text-text-2">
      {failure ?? (needsPermissions ? "Waiting for permissions in the Plugins tab in Settings." : "Starting")}
    </span>
  );

  return (
    <section className="panel p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="display text-sm font-semibold tracking-[0.08em] truncate flex-1">{plugin.manifest.name}</h3>
        <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        {floatable && (
          <button
            className={`chip cursor-pointer hover:opacity-80 ${popped ? "chip-accent" : ""}`}
            aria-pressed={popped}
            title={popped ? "Close the floating window" : "Pop out into a floating window"}
            aria-label={`${popped ? "Close" : "Pop out"} ${plugin.manifest.name}`}
            onClick={() => popPlugin(popped ? null : plugin.id)}
          >
            ⧉
          </button>
        )}
      </div>
      {popped ? <span className="text-[0.7rem] text-text-2">Showing in a floating window.</span> : body}
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
