import { rectSortingStrategy } from "@dnd-kit/sortable";
import { useEffect, useRef } from "react";
import { applyLayout, section, togglePinned, toggleHidden, withOrder } from "../layout";
import { PANEL_SANDBOX_URL } from "../panel";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { PluginNodeView } from "./PluginNode";
import { Sortable } from "./Sortable";

function PluginWebview({ plugin }: { plugin: PluginRecord }) {
  const mountPanel = useStore((s) => s.mountPanel);
  const ready = useStore((s) => s.pluginPanels[plugin.id] !== undefined);
  const frame = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (ready) mountPanel(plugin.id, frame.current);
    return () => mountPanel(plugin.id, null);
  }, [plugin.id, ready]);

  return (
    <iframe
      ref={frame}
      src={PANEL_SANDBOX_URL}
      sandbox="allow-scripts"
      allow=""
      title={`${plugin.manifest.name} panel`}
      className="block h-24 w-full border-0 bg-transparent transition-[height] duration-150"
    />
  );
}

export function PluginPanel({ plugin }: { plugin: PluginRecord }) {
  const { customising, mutateLayout, engine } = useStore();
  const pinned = section(engine?.settings.layout, "plugins").pinned.includes(plugin.id);
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const mayViewCameras = plugin.granted.includes("camera:view");
  const webview = plugin.files.includes("panel.html");

  const body = webview ? (
    <PluginWebview plugin={plugin} />
  ) : tree ? (
    <PluginNodeView node={tree} pluginId={plugin.id} mayViewCameras={mayViewCameras} />
  ) : (
    <span className="text-[0.7rem] text-text-2">{failure ?? "Starting"}</span>
  );

  return (
    <section className="panel p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="display text-sm font-semibold tracking-[0.08em] truncate flex-1">{plugin.manifest.name}</h3>
        {customising ? (
          <>
            <button
              className={`btn !py-1 !px-2 !text-[0.6rem] ${pinned ? "btn-primary" : ""}`}
              aria-pressed={pinned}
              onClick={() => mutateLayout("plugins", (s) => togglePinned(s, plugin.id))}
            >
              {pinned ? "Pinned" : "Pin"}
            </button>
            <button
              className="btn !py-1 !px-2 !text-[0.6rem]"
              aria-label={`Hide ${plugin.manifest.name}`}
              onClick={() => mutateLayout("plugins", (s) => toggleHidden(s, plugin.id))}
            >
              Hide
            </button>
          </>
        ) : (
          <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        )}
      </div>
      {body}
    </section>
  );
}

export function PluginSection() {
  const { engine, customising, mutateLayout } = useStore();
  const drawn = (engine?.plugins ?? []).filter(
    (p) => p.enabled && p.manifest.surfaces.includes("panel") && (p.files.includes("plugin.js") || p.files.includes("panel.html")),
  );
  const { visible } = applyLayout(drawn, section(engine?.settings.layout, "plugins"));
  if (drawn.length === 0) return null;
  return (
    <Sortable
      ids={visible.map((p) => p.id)}
      strategy={rectSortingStrategy}
      disabled={!customising}
      onReorder={(ids) => mutateLayout("plugins", (s) => withOrder(s, ids))}
    >
      <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr))]">
        {visible.map((plugin) => (
          <PluginPanel key={plugin.id} plugin={plugin} />
        ))}
      </div>
    </Sortable>
  );
}
