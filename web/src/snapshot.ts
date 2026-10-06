import { useEffect, useRef, useState } from "react";
import { useStore } from "./store";

const PRELOAD_MARGIN = "300px";

export function useLazySnapshot<Element extends HTMLElement>(monitorId: string, id: string) {
  const url = useStore((s) => s.snapshotCache[id]);
  const fetchSnapshot = useStore((s) => s.fetchSnapshot);
  const reconnecting = useStore((s) => s.reconnecting);
  const ref = useRef<Element>(null);
  const [nearViewport, setNearViewport] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setNearViewport(entry.isIntersecting), { rootMargin: PRELOAD_MARGIN });
    observer.observe(ref.current!);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (nearViewport && !reconnecting) fetchSnapshot(monitorId, id);
  }, [monitorId, id, nearViewport, reconnecting]);

  return { ref, url };
}
