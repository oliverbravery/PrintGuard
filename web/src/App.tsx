import { BootScreen } from "./components/BootScreen";
import { Dashboard } from "./components/Dashboard";
import { useStore } from "./store";

export function App() {
  const phase = useStore((s) => s.phase);
  return phase === "ready" ? <Dashboard /> : <BootScreen />;
}
