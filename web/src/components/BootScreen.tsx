import { useStore } from "../store";
import { Wordmark } from "./Wordmark";

export function BootScreen() {
  const bootMsg = useStore((s) => s.bootMsg);
  return (
    <div className="min-h-dvh grid place-items-center">
      <div className="text-center">
        <Wordmark size="text-5xl" />
        <div className="mono text-xs mt-6 text-text-1 boot-cursor">{bootMsg}</div>
      </div>
    </div>
  );
}
