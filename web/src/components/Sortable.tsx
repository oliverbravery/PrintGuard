import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  type SortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ReactElement, ReactNode } from "react";
import { sharesPinning } from "../layout";
import { SectionHead } from "./SectionHead";

export { horizontalListSortingStrategy, rectSortingStrategy } from "@dnd-kit/sortable";

type SortableState = ReturnType<typeof useSortable>;

export interface SortableHandle {
  setNodeRef: SortableState["setNodeRef"];
  style: React.CSSProperties;
  isDragging: boolean;
  attributes: SortableState["attributes"];
  listeners: SortableState["listeners"];
}

export function Sortable({
  ids,
  pinned,
  strategy,
  onReorder,
  disabled,
  children,
}: {
  ids: string[];
  pinned: string[];
  strategy: SortingStrategy;
  onReorder: (ids: string[]) => void;
  disabled: boolean;
  children: ReactNode;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  if (disabled) return <>{children}</>;
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from !== -1 && to !== -1) onReorder(arrayMove(ids, from, to));
  };
  const closestInSameGroup: CollisionDetection = (args) =>
    closestCenter({ ...args, droppableContainers: args.droppableContainers.filter((tile) => sharesPinning(pinned, String(args.active.id), String(tile.id))) });
  return (
    <DndContext sensors={sensors} collisionDetection={closestInSameGroup} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={strategy}>
        {children}
      </SortableContext>
    </DndContext>
  );
}

export function SortableItem({ id, children }: { id: string; children: (handle: SortableHandle) => ReactElement }) {
  const { setNodeRef, transform, transition, isDragging, attributes, listeners } = useSortable({ id });
  return children({
    setNodeRef,
    isDragging,
    attributes,
    listeners,
    style: { transform: CSS.Transform.toString(transform), transition },
  });
}

export function HiddenTray({
  label,
  items,
  onShow,
}: {
  label: string;
  items: { id: string; name: string }[];
  onShow: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mt-6">
      <SectionHead title={label} />
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <button key={item.id} className="btn !py-1.5 !px-3 !text-[0.68rem]" onClick={() => onShow(item.id)}>
            {item.name} · show
          </button>
        ))}
      </div>
    </div>
  );
}
