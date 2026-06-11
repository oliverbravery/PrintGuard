import { BootScreen } from "./components/BootScreen";
import { Dashboard } from "./components/Dashboard";
import { ModePicker } from "./components/ModePicker";
import { useStore } from "./store";

export function App() {
  const phase = useStore((s) => s.phase);
  if (phase === "pick") return <ModePicker />;
  if (phase === "ready") return <Dashboard />;
  return <BootScreen />;
}
