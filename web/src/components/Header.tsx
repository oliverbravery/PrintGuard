import { useStore } from "../store";

export function Wordmark({ size = "text-xl" }: { size?: string }) {
  return (
    <span className={`display font-bold ${size} leading-none select-none`}>
      PRINT<span className="text-accent">/</span>GUARD
    </span>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div className="hidden md:flex flex-col items-end leading-tight">
      <span className="mono text-[0.78rem] text-text-0">{value}</span>
      <span className="label">{label}</span>
    </div>
  );
}

export function Header() {
  const { engine, mode, leaveMode, openDialog } = useStore();
  const stats = engine?.stats;
  return (
    <header className="sticky top-0 z-30 border-b border-line-0 bg-ink-0/90 backdrop-blur-sm">
      <div className="mx-auto max-w-[1500px] px-4 sm:px-6 py-3 flex items-center gap-4">
        <Wordmark />
        <button
          className="chip chip-accent cursor-pointer hover:opacity-80"
          title="Switch mode"
          onClick={leaveMode}
        >
          {mode === "hub" ? "hub" : "local"} ▾
        </button>
        <div className="flex-1" />
        {stats && (
          <div className="flex items-center gap-5 mr-2">
            <Readout label="capacity" value={`${stats.capacity_fps.toFixed(1)} fps`} />
            <Readout label="latency" value={`${stats.infer_ms.toFixed(0)} ms`} />
            <Readout label="workers" value={String(stats.workers)} />
          </div>
        )}
        <button className="btn" onClick={() => openDialog("cameras")}>
          Cameras
        </button>
        <button className="btn btn-primary" onClick={() => openDialog("printer")}>
          + Printer
        </button>
        <button className="btn" onClick={() => openDialog("settings")} aria-label="Settings">
          ⚙
        </button>
      </div>
    </header>
  );
}
