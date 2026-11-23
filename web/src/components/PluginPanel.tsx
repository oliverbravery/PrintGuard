import { useEffect, useRef } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { LayoutRow, useReorder } from "./LayoutControls";
import { ListHead } from "./Page";
import { PluginNodeView } from "./PluginNode";
import { Sortable, SortableItem, type SortableHandle, verticalListSortingStrategy } from "./Sortable";

function PluginWebview({ plugin, hidden }: { plugin: PluginRecord; hidden: boolean }) {
  const mountPanel = useStore((s) => s.mountPanel);
  const ready = useStore((s) => s.pluginPanels[plugin.id] !== undefined);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ready) mountPanel(plugin.id, container.current);
    return () => mountPanel(plugin.id, null);
  }, [plugin.id, ready]);

  return <div ref={container} hidden={hidden} />;
}

function PluginRow({ plugin, handle, visible, group }: { plugin: PluginRecord; handle?: SortableHandle; visible: string[]; group: string[] }) {
  const tree = useStore((s) => s.pluginTrees[plugin.id]);
  const assets = useStore((s) => s.pluginAssets[plugin.id]);
  const failure = useStore((s) => s.pluginFailures[plugin.id]) ?? plugin.failure;
  const panel = plugin.files.includes("panel.html");
  const item = tree?.type === "item" ? tree : null;
  const image = item?.image?.startsWith("data:")
    ? item.image
    : item?.image && assets && Object.hasOwn(assets, item.image)
      ? assets[item.image]
      : undefined;
  return (
    <LayoutRow
      id={plugin.id}
      name={plugin.manifest.name}
      handle={handle}
      visible={visible}
      group={group}
      thumb={item && <div className="aspect-video w-20 shrink-0 overflow-hidden border border-line-0 bg-ink-1">{image && <img src={image} alt="" className="size-full object-contain" />}</div>}
      below={
        item?.actions?.length ? (
          <div className="flex flex-wrap justify-end gap-1">
            {item.actions.map((action, index) => (
              <PluginNodeView key={index} plugin={plugin} node={action} panel={panel} />
            ))}
          </div>
        ) : undefined
      }
    >
      <span className="flex items-center gap-2">
        <h3 className="label truncate">{plugin.manifest.name}</h3>
        {!plugin.verified && <span className="chip">third party</span>}
      </span>
      {item ? (
        <>
          <span className="truncate font-bold">{item.title}</span>
          {item.description && <span className="mono truncate text-xs text-text-2">{item.description}</span>}
        </>
      ) : tree ? (
        <PluginNodeView plugin={plugin} node={tree} panel={panel} />
      ) : (
        (failure || !panel) && <span className="text-sm text-text-2">{failure ?? "Starting"}</span>
      )}
      {panel && <PluginWebview plugin={plugin} hidden={Boolean(tree)} />}
    </LayoutRow>
  );
}

export function PluginList({ plugins, visible, pinned }: { plugins: PluginRecord[]; visible: string[]; pinned: string[] }) {
  const customising = useStore((s) => s.customising);
  const group = plugins.map((plugin) => plugin.id);
  const reorder = useReorder(visible);
  if (plugins.length === 0) return null;
  return (
    <section aria-label="Plugins">
      <div className="surface sticky top-0 z-[5]">
        <ListHead title={`Plugins · ${plugins.length}`} />
      </div>
      <Sortable ids={group} pinned={pinned} strategy={verticalListSortingStrategy} disabled={!customising} onReorder={reorder}>
        <ul>
          {plugins.map((plugin) =>
            customising ? (
              <SortableItem key={plugin.id} id={plugin.id}>
                {(handle) => <PluginRow plugin={plugin} handle={handle} visible={visible} group={group} />}
              </SortableItem>
            ) : (
              <PluginRow key={plugin.id} plugin={plugin} visible={visible} group={group} />
            ),
          )}
        </ul>
      </Sortable>
    </section>
  );
}
