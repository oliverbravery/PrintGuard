import { Bug, Ellipsis } from "lucide-react";
import { useStore } from "../store";
import { applyTheme, GLASS, nextScheme } from "../theme";
import { GLASS_TUNER, GlassTuner } from "./GlassTuner";
import { HeaderActions } from "./Nav";
import { Wordmark } from "./Wordmark";

function Readout({
  label,
  value,
  className = "",
  onClick,
}: {
  label: string;
  value: string;
  className?: string;
  onClick?: () => void;
}) {
  const content = (
    <>
      <span className="mono block whitespace-nowrap text-[0.78rem] text-text-0">{value}</span>
      <span className="label block">{label}</span>
    </>
  );
  return onClick ? (
    <button
      className={`cursor-pointer text-right leading-tight hover:opacity-75 ${className}`}
      onClick={onClick}
      title="Choose model runtime"
      aria-label={`Compute: ${value}. Choose model runtime`}
    >
      {content}
    </button>
  ) : (
    <div className={`text-right leading-tight ${className}`}>{content}</div>
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
  const stored = useStore((s) => s.engine?.settings.glass);
  const updateSettings = useStore((s) => s.updateSettings);
  const glyph = theme === "light" ? "☀" : theme === "dark" ? "☾" : theme === GLASS ? "◈" : themes.some((t) => t.id === theme) ? "✦" : "◐";
  return (
    <>
      <button
        className="chip tuner-anchor cursor-pointer hover:opacity-80"
        title={`Theme: ${theme}, tap to switch`}
        aria-label="Switch theme"
        onClick={() => {
          const next = nextScheme(theme);
          applyTheme(next, themes, stored);
          updateSettings({ theme: next });
          if (next === GLASS) document.getElementById(GLASS_TUNER)?.showPopover();
        }}
      >
        {glyph}
      </button>
      <GlassTuner />
    </>
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

function ReportChip() {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <button
      className="chip inline-flex cursor-pointer items-center hover:opacity-80"
      title="Report a bug"
      aria-label="Report a bug"
      onClick={() => openDialog("report")}
    >
      <Bug className="h-[1.15em] w-[1.15em]" aria-hidden />
    </button>
  );
}

function MoreChip() {
  const openDialog = useStore((s) => s.openDialog);
  const available = useStore((s) => s.engine?.update?.available ?? false);
  return (
    <button
      className={`chip inline-flex cursor-pointer items-center hover:opacity-80 sm:hidden ${available ? "chip-accent" : ""}`}
      title="More"
      aria-label={available ? "More, update available" : "More"}
      onClick={() => openDialog("more")}
    >
      <Ellipsis className="h-[1.15em] w-[1.15em]" aria-hidden />
    </button>
  );
}

export function Header() {
  const { engine, openSettings } = useStore();
  const stats = engine?.stats;
  return (
    <header className="sticky top-0 z-30 border-b border-line-0 bg-ink-0/90 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1500px] items-center gap-x-3 px-4 py-3 sm:px-6">
        <Wordmark />
        <div className="hidden sm:contents">
          <VersionChip />
          <ThemeToggle />
          <CustomiseToggle />
          <GuideChip />
          <ReportChip />
        </div>
        <div className="flex-1" />
        {stats && (
          <div className="hidden items-center gap-5 sm:flex lg:mr-2">
            <Readout
              label="compute"
              value={stats.inference_device.toLowerCase()}
              className="hidden xl:block"
              onClick={() => openSettings("advanced")}
            />
            <Readout label="capacity" value={`${stats.capacity_fps.toFixed(1)} fps`} />
            <Readout label="latency" value={`${stats.infer_ms.toFixed(0)} ms`} />
          </div>
        )}
        <HeaderActions />
        <MoreChip />
      </div>
    </header>
  );
}
