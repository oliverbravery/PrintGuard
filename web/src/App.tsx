import { BootScreen } from "./components/BootScreen";
import { Dashboard } from "./components/Dashboard";
import { Home } from "./components/Home";
import { useStore } from "./store";

export function App() {
  const phase = useStore((s) => s.phase);
  if (phase === "pick") return <Home />;
  if (phase === "ready") return <Dashboard />;
  return <BootScreen />;
}
