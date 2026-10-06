import { useStore } from "../store";

export function SaveStatus({ scope }: { scope: string }) {
  const saving = useStore((s) => scope in s.optimistic);
  const savedAt = useStore((s) => s.savedAt[scope]);
  if (saving) {
    return <span className="mono text-[0.62rem] text-text-2 boot-cursor">saving</span>;
  }
  if (savedAt) {
    const time = new Date(savedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return <span className="chip chip-ok">saved ✓ {time}</span>;
  }
  return null;
}
