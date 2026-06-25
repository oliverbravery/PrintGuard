import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
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
  strategy,
  onReorder,
  disabled,
  children,
}: {
  ids: string[];
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
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
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
      <div className="mb-2.5 flex items-center gap-3">
        <h2 className="display text-xs font-semibold tracking-[0.24em] text-text-2">{label}</h2>
        <div className="hairline flex-1" />
      </div>
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
