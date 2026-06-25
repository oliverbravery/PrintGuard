import { useStore } from "../store";

export function SaveStatus() {
  const { optimistic, savedAt } = useStore();
  if (Object.keys(optimistic).length > 0) {
    return <span className="mono text-[0.62rem] text-text-2 boot-cursor">saving</span>;
  }
  if (savedAt) {
    const time = new Date(savedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return <span className="chip chip-ok">saved ✓ {time}</span>;
  }
  return null;
}
