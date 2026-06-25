import { cardButton } from "../a11y";
import { applyLayout, section, toggleHidden, withOrder } from "../layout";
import { useStore } from "../store";
import type { Camera, CameraSource } from "../types";
import { horizontalListSortingStrategy, Sortable, SortableItem, type SortableHandle } from "./Sortable";

export function sourceLabel(source: CameraSource): string {
  if (source.kind === "device") return source.label || "device camera";
  if (source.kind === "path") return `path://${source.path}`;
  if (source.kind === "bambu") return `bambu://${source.host ?? ""}`;
  return source.url ? source.url.replace(/\/\/[^/@]+@/, "//") : source.kind;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="leading-tight">
      <div className="mono text-[0.72rem] text-text-0">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function CameraCard({ camera }: { camera: Camera }) {
  const { openDialog, customising, mutateLayout } = useStore();

  const content = (handle?: SortableHandle) => (
    <>
      {handle ? (
        <button
          className="btn !py-1 !px-2 cursor-grab touch-none"
          aria-label={`Drag ${camera.name} to reorder`}
          {...handle.attributes}
          {...handle.listeners}
        >
          ⠿
        </button>
      ) : (
        <span
          aria-hidden
          className={`led ${camera.inferring ? "led-infer" : camera.online ? "led-on" : "led-off"}`}
          title={camera.online ? "online" : "offline"}
        />
      )}
      <div className="order-1 min-w-0 flex-1 leading-tight sm:flex-none sm:w-36">
        <div className="display text-sm font-semibold truncate">{camera.name}</div>
        <div className="mono text-[0.6rem] text-text-2 truncate">{sourceLabel(camera.source)}</div>
      </div>
      {handle ? (
        <button
          className="btn order-2 !py-1 !px-2 !text-[0.6rem] sm:order-last"
          aria-label={`Hide ${camera.name}`}
          onClick={() => mutateLayout("cameras", (s) => toggleHidden(s, camera.id))}
        >
          Hide
        </button>
      ) : (
        <span className={`chip order-2 sm:order-last ${camera.in_use ? "chip-accent" : ""}`}>
          {camera.in_use ? "in use" : "idle"}
        </span>
      )}
      <div className="order-3 flex w-full items-center gap-4 sm:order-2 sm:w-auto">
        <Stat label="max" value={`${camera.max_fps.toFixed(0)}`} />
        <Stat label="target" value={camera.in_use ? camera.target_fps.toFixed(1) : "—"} />
        <Stat label="actual" value={camera.in_use ? camera.achieved_fps.toFixed(1) : "—"} />
      </div>
    </>
  );

  if (!customising)
    return (
      <div
        {...cardButton(() => openDialog("cameras", camera.id), `Edit camera ${camera.name}`)}
        className="panel flex w-60 shrink-0 snap-start cursor-pointer flex-wrap items-center gap-x-4 gap-y-2.5 px-3.5 py-2.5 transition-colors hover:border-accent sm:w-auto"
      >
        {content()}
      </div>
    );

  return (
    <SortableItem id={camera.id}>
      {(handle) => (
        <div
          ref={handle.setNodeRef}
          style={handle.style}
          className={`panel flex w-60 shrink-0 snap-start flex-wrap items-center gap-x-4 gap-y-2.5 px-3.5 py-2.5 sm:w-auto ${handle.isDragging ? "z-10 opacity-90 shadow-xl" : ""}`}
        >
          {content(handle)}
        </div>
      )}
    </SortableItem>
  );
}

export function CameraRail() {
  const { engine, openDialog, customising, mutateLayout } = useStore();
  const cameras = engine?.cameras ?? [];
  const { visible } = applyLayout(cameras, section(engine?.settings.layout, "cameras"));
  return (
    <section className="mx-auto max-w-[1500px] px-4 sm:px-6 pt-5">
      <div className="flex items-center gap-3 mb-2.5">
        <h2 className="display text-xs font-semibold tracking-[0.24em] text-text-2">CAMERA REGISTRY</h2>
        <div className="hairline flex-1" />
        <button className="btn !py-1.5 !px-3 !text-[0.68rem]" onClick={() => openDialog("cameras")}>
          + Camera
        </button>
      </div>
      {cameras.length === 0 ? (
        <p className="mono text-[0.7rem] text-text-2 py-1.5">no cameras registered</p>
      ) : (
        <Sortable
          ids={visible.map((c) => c.id)}
          strategy={horizontalListSortingStrategy}
          disabled={!customising}
          onReorder={(ids) => mutateLayout("cameras", (s) => withOrder(s, ids))}
        >
          <div className="flex gap-3 overflow-x-auto snap-x snap-mandatory pb-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {visible.map((camera) => (
              <CameraCard key={camera.id} camera={camera} />
            ))}
          </div>
        </Sortable>
      )}
    </section>
  );
}
