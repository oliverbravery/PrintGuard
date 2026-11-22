import { RouterProvider } from "react-router";
import { BootScreen } from "./components/BootScreen";
import { router } from "./router";
import { useStore } from "./store";

export function App() {
  const phase = useStore((s) => s.phase);
  return phase === "ready" ? <RouterProvider router={router} /> : <BootScreen />;
}
