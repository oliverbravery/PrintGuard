import { useStore } from "../store";
import { Wordmark } from "./Header";

export function BootScreen() {
  const { phase, bootMsg, leaveMode } = useStore();
  return (
    <div className="min-h-screen grid place-items-center">
      <div className="text-center">
        <Wordmark size="text-5xl" />
        <div className={`mono text-xs mt-6 ${phase === "error" ? "text-bad" : "text-text-1 boot-cursor"}`}>
          {phase === "error" ? `boot failed — ${bootMsg}` : bootMsg || "initialising"}
        </div>
        {phase === "error" && (
          <button className="btn mt-6" onClick={leaveMode}>
            Back to mode select
          </button>
        )}
      </div>
    </div>
  );
}
