import { useEffect, useRef } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { Cell } from "./FleetLedger";
import { LayoutControls, useReorder } from "./LayoutControls";
import { ListHead } from "./Page";
import { PluginNodeView } from "./PluginNode";
import { Sortable, SortableItem, type SortableHandle, verticalListSortingStrategy } from "./Sortable";

const COLUMNS = "grid-cols-[6.5rem_minmax(0,1fr)_auto] @3xl:grid-cols-[8rem_minmax(0,1fr)_auto]";

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
  const name = (
    <span className="flex items-center gap-2">
      <h3 className="label truncate">{plugin.manifest.name}</h3>
      {!plugin.verified && <span className="chip">third party</span>}
    </span>
  );
  return (
    <li
      ref={handle?.setNodeRef}
      style={handle?.style}
      className={`relative grid border-b border-line-0 ${COLUMNS} ${handle?.isDragging ? "z-10 bg-ink-1" : "hover:bg-ink-1"}`}
    >
      {item && (
        <div className="p-2">
          <div className="aspect-video overflow-hidden border border-line-0 bg-ink-1">{image && <img src={image} alt="" className="size-full object-contain" />}</div>
        </div>
      )}
      <div
        className={`flex min-w-0 flex-col justify-center gap-1 ${item ? "border-l border-line-0 px-3 py-2" : `px-4 py-3 ${handle ? "col-span-2" : "col-span-3"}`}`}
      >
        {name}
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
      </div>
      {(handle || item) && (
        <Cell className="items-end">
          {handle ? (
            <LayoutControls id={plugin.id} name={plugin.manifest.name} handle={handle} visible={visible} group={group} />
          ) : (
            <div className="flex flex-wrap justify-end gap-1">
              {item!.actions?.map((action, index) => (
                <PluginNodeView key={index} plugin={plugin} node={action} panel={panel} />
              ))}
            </div>
          )}
        </Cell>
      )}
    </li>
  );
}

export function PluginLedger({ plugins, visible, pinned }: { plugins: PluginRecord[]; visible: string[]; pinned: string[] }) {
  const customising = useStore((s) => s.customising);
  const group = plugins.map((plugin) => plugin.id);
  const reorder = useReorder(visible);
  if (plugins.length === 0) return null;
  return (
    <section aria-label="Plugins" className="@container border-b border-rule">
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
