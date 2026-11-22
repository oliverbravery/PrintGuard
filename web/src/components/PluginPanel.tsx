import { useEffect, useRef } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { PluginNodeView } from "./PluginNode";
import { LayoutControls } from "./LayoutControls";
import { SortableItem, type SortableHandle } from "./Sortable";

function PluginWebview({ plugin }: { plugin: PluginRecord }) {
  const mountPanel = useStore((s) => s.mountPanel);
  const ready = useStore((s) => s.pluginPanels[plugin.id] !== undefined);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ready) mountPanel(plugin.id, container.current);
    return () => mountPanel(plugin.id, null);
  }, [plugin.id, ready]);

  return <div ref={container} />;
}

export function PluginPanel({ plugin, visible, group }: { plugin: PluginRecord; visible: string[]; group: string[] }) {
  const customising = useStore((s) => s.customising);
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const webview = plugin.files.includes("panel.html");
  const body = webview ? (
    <PluginWebview plugin={plugin} />
  ) : tree ? (
    <PluginNodeView plugin={plugin} node={tree} />
  ) : (
    <span className="text-sm text-text-2">{failure ?? "Starting"}</span>
  );
  const content = (handle?: SortableHandle) => (
    <section
      ref={handle?.setNodeRef}
      style={handle?.style}
      className={`flex flex-col border-b border-line-0 bg-ink-0 md:border-r ${handle?.isDragging ? "z-10" : ""}`}
    >
      <div className="flex min-h-11 items-center gap-2 border-b border-line-0 px-4 py-1.5">
        <h3 className="min-w-0 flex-1 truncate text-sm font-bold">{plugin.manifest.name}</h3>
        {handle ? (
          <LayoutControls id={plugin.id} name={plugin.manifest.name} handle={handle} visible={visible} group={group} />
        ) : (
          <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        )}
      </div>
      <div className="flex flex-1 flex-col justify-center p-4">{body}</div>
    </section>
  );
  if (!customising) return content();
  return <SortableItem id={plugin.id}>{(handle) => content(handle)}</SortableItem>;
}
