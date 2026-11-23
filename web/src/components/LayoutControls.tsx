import { ArrowDown, ArrowUp, GripVertical } from "lucide-react";
import type { ReactNode } from "react";
import { moveWithinGroup, reorderGroup, section, togglePinned, toggleHidden } from "../layout";
import { useStore } from "../store";
import type { SortableHandle } from "./Sortable";

export function useReorder(visible: string[]) {
  const mutateLayout = useStore((s) => s.mutateLayout);
  return (ids: string[]) => mutateLayout((sec) => reorderGroup(sec, visible, ids));
}

function LayoutControls({
  id,
  name,
  handle,
  visible,
  group,
}: {
  id: string;
  name: string;
  handle: SortableHandle;
  visible: string[];
  group: string[];
}) {
  const engine = useStore((s) => s.engine);
  const mutateLayout = useStore((s) => s.mutateLayout);
  const pinned = section(engine?.settings.layout).pinned;
  const isPinned = pinned.includes(id);
  const reorder = useReorder(visible);
  const move = (by: -1 | 1) => moveWithinGroup(group, pinned, id, by);
  return (
    <div className="relative z-[1] flex flex-wrap items-center justify-end gap-1">
      <button className="btn-inline cursor-grab touch-none" aria-label={`Drag ${name} to reorder`} {...handle.attributes} {...handle.listeners}>
        <GripVertical size={14} aria-hidden />
      </button>
      {([-1, 1] as const).map((by) => {
        const next = move(by);
        const Icon = by < 0 ? ArrowUp : ArrowDown;
        return (
          <button key={by} className="btn-inline" aria-label={`Move ${name} ${by < 0 ? "up" : "down"}`} disabled={!next} onClick={() => next && reorder(next)}>
            <Icon size={14} aria-hidden />
          </button>
        );
      })}
      <button className="btn-inline" aria-pressed={isPinned} aria-label={`${isPinned ? "Pinned" : "Pin"} ${name}`} onClick={() => mutateLayout((s) => togglePinned(s, id))}>
        {isPinned ? "Pinned" : "Pin"}
      </button>
      <button className="btn-inline" aria-label={`Hide ${name}`} onClick={() => mutateLayout((s) => toggleHidden(s, id))}>
        Hide
      </button>
    </div>
  );
}

export function LayoutRow({
  id,
  name,
  handle,
  visible,
  group,
  thumb,
  trailing,
  below,
  children,
}: {
  id: string;
  name: string;
  handle?: SortableHandle;
  visible: string[];
  group: string[];
  thumb?: ReactNode;
  trailing?: ReactNode;
  below?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li ref={handle?.setNodeRef} style={handle?.style} className={`list-row flex-wrap gap-y-2 ${handle?.isDragging ? "z-10 bg-ink-1" : ""}`}>
      {thumb}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">{children}</div>
      {trailing}
      {(handle || below) && (
        <div className="basis-full">{handle ? <LayoutControls id={id} name={name} handle={handle} visible={visible} group={group} /> : below}</div>
      )}
    </li>
  );
}
