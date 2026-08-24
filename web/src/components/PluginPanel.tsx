import { useEffect, useRef } from "react";
import { section, togglePinned, toggleHidden } from "../layout";
import { PANEL_SANDBOX_URL } from "../panel";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { PluginNodeView } from "./PluginNode";
import { SortableItem, type SortableHandle } from "./Sortable";

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
  const pinned = section(engine?.settings.layout, "monitors").pinned.includes(plugin.id);
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const webview = plugin.files.includes("panel.html");

  const body = webview ? (
    <PluginWebview plugin={plugin} />
  ) : tree ? (
    <PluginNodeView plugin={plugin} node={tree} />
  ) : (
    <span className="text-[0.7rem] text-text-2">{failure ?? "Starting"}</span>
  );

  const content = (handle?: SortableHandle) => (
    <>
      <div className="flex items-center gap-2">
        {handle && (
          <button
            className="btn !py-1 !px-2 cursor-grab touch-none"
            aria-label={`Drag ${plugin.manifest.name} to reorder`}
            {...handle.attributes}
            {...handle.listeners}
          >
            ⠿
          </button>
        )}
        <h3 className="display text-sm font-semibold tracking-[0.08em] truncate flex-1">{plugin.manifest.name}</h3>
        {handle ? (
          <>
            <button
              className={`btn !py-1 !px-2 !text-[0.6rem] ${pinned ? "!border-accent !text-accent" : ""}`}
              aria-pressed={pinned}
              aria-label={`${pinned ? "Pinned" : "Pin"} ${plugin.manifest.name}`}
              onClick={() => mutateLayout("monitors", (s) => togglePinned(s, plugin.id))}
            >
              {pinned ? "Pinned" : "Pin"}
            </button>
            <button
              className="btn !py-1 !px-2 !text-[0.6rem]"
              aria-label={`Hide ${plugin.manifest.name}`}
              onClick={() => mutateLayout("monitors", (s) => toggleHidden(s, plugin.id))}
            >
              Hide
            </button>
          </>
        ) : (
          <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        )}
      </div>
      <div className="flex flex-1 flex-col justify-center">{body}</div>
    </>
  );

  if (!customising) return <section className="panel flex flex-col gap-3 p-4">{content()}</section>;

  return (
    <SortableItem id={plugin.id}>
      {(handle) => (
        <section
          ref={handle.setNodeRef}
          style={handle.style}
          className={`panel flex flex-col gap-3 p-4 ${pinned ? "!border-accent" : ""} ${handle.isDragging ? "z-10 opacity-90 shadow-xl" : ""}`}
        >
          {content(handle)}
        </section>
      )}
    </SortableItem>
  );
}
