import { type RefObject, useEffect } from "react";

export function useScrollEdges(ref: RefObject<HTMLElement | null>, key: number): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const start = el.scrollLeft > 1;
      const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
      if (start || end) el.dataset.overflow = start && end ? "both" : start ? "start" : "end";
      else delete el.dataset.overflow;
    };
    const observer = new ResizeObserver(update);
    observer.observe(el);
    for (const child of el.children) observer.observe(child);
    el.addEventListener("scroll", update, { passive: true });
    update();
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", update);
    };
  }, [ref, key]);
}
