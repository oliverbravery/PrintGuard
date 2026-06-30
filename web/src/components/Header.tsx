import { useStore } from "../store";
import { applyTheme, nextScheme } from "../theme";

export function Wordmark({ size = "text-xl" }: { size?: string }) {
  return (
    <span className={`display font-bold ${size} leading-none select-none`}>
      PRINT<span className="text-accent">/</span>GUARD
    </span>
  );
}

function Readout({ label, value, className = "hidden md:block" }: { label: string; value: string; className?: string }) {
  return (
    <div className={`text-right leading-tight ${className}`}>
      <span className="mono block text-[0.78rem] text-text-0">{value}</span>
      <span className="label block">{label}</span>
    </div>
  );
}

export function HeaderActions({ className }: { className?: string }) {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <nav className={className}>
      <button className="btn max-md:w-full max-md:py-2.5" onClick={() => openDialog("cameras")}>
        Cameras
      </button>
      <button className="btn max-md:w-full max-md:py-2.5" onClick={() => openDialog("printers")}>
        Printers
      </button>
      <button className="btn btn-primary max-md:w-full max-md:py-2.5" onClick={() => openDialog("monitor")}>
        + Monitor
      </button>
      <button className="btn max-md:w-full max-md:py-2.5" onClick={() => openDialog("settings")} aria-label="Settings">
        <span className="md:hidden">Settings</span>
        <span className="hidden md:inline">⚙</span>
      </button>
    </nav>
  );
}

export function MobileActionBar() {
  return (
    <HeaderActions className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 gap-2 border-t border-line-0 bg-ink-0/95 px-4 pt-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))] backdrop-blur-sm md:hidden" />
  );
}

function VersionChip() {
  const version = useStore((s) => s.engine?.version);
  const update = useStore((s) => s.engine?.update);
  const openDialog = useStore((s) => s.openDialog);
  if (!version) return null;
  const available = update?.available;
  return (
    <button
      className={`chip cursor-pointer hover:opacity-80 ${available ? "chip-accent" : ""}`}
      title={available ? `Update available: v${update!.latest}` : `PrintGuard v${version}`}
      onClick={() => openDialog("update")}
    >
      {available ? `↑ v${update!.latest}` : `v${version}`}
    </button>
  );
}

function ThemeToggle() {
  const theme = useStore((s) => s.engine?.settings.theme ?? "system");
  const themes = useStore((s) => s.engine?.settings.themes ?? []);
  const send = useStore((s) => s.send);
  const glyph = theme === "light" ? "☀" : theme === "dark" ? "☾" : themes.some((t) => t.id === theme) ? "✦" : "◐";
  return (
    <button
      className="chip cursor-pointer hover:opacity-80"
      title={`Theme: ${theme} — tap to switch`}
      aria-label="Switch theme"
      onClick={() => {
        const next = nextScheme(theme);
        applyTheme(next, themes);
        send({ cmd: "settings.update", patch: { theme: next } });
      }}
    >
      {glyph}
    </button>
  );
}

function CustomiseToggle() {
  const engine = useStore((s) => s.engine);
  const customising = useStore((s) => s.customising);
  const setCustomising = useStore((s) => s.setCustomising);
  if (!engine) return null;
  return (
    <button
      className={`chip cursor-pointer hover:opacity-80 ${customising ? "chip-accent" : ""}`}
      title="Customise layout"
      aria-label="Customise layout"
      aria-pressed={customising}
      onClick={() => setCustomising(!customising)}
    >
      ▦
    </button>
  );
}

function GuideChip() {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <button
      className="chip cursor-pointer hover:opacity-80"
      title="Open the guide"
      aria-label="Open the guide"
      onClick={() => openDialog("guide")}
    >
      ?
    </button>
  );
}

export function Header() {
  const { engine, mode, leaveMode } = useStore();
  const stats = engine?.stats;
  return (
    <header className="sticky top-0 z-30 border-b border-line-0 bg-ink-0/90 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1500px] items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
        <Wordmark />
        {mode === "local" && (
          <button
            className="chip chip-accent cursor-pointer hover:opacity-80"
            title="Back to start"
            onClick={leaveMode}
          >
            local ▾
          </button>
        )}
        <VersionChip />
        <ThemeToggle />
        <CustomiseToggle />
        <GuideChip />
        <div className="flex-1" />
        {stats && (
          <div className="flex items-center gap-5 md:mr-2">
            <Readout label="capacity" value={`${stats.capacity_fps.toFixed(1)} fps`} className="hidden min-[400px]:block" />
            <Readout label="latency" value={`${stats.infer_ms.toFixed(0)} ms`} />
            <Readout label="workers" value={String(stats.workers)} />
          </div>
        )}
        <HeaderActions className="hidden md:flex md:items-center md:gap-2 lg:gap-3" />
      </div>
    </header>
  );
}
