import { Bug, Camera, CircleHelp, Layers, type LucideIcon, Printer, ScanEye, Settings } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Link, Outlet, useLocation } from "react-router";
import { useStore } from "../store";
import { applyTheme, GLASS, nextScheme } from "../theme";
import { useTopModal } from "./Dialog";
import { GLASS_TUNER, GlassTuner } from "./GlassTuner";
import { GuideDialog } from "./GuideDialog";
import { IntroDialog } from "./IntroDialog";
import { MonitorDialog } from "./MonitorDialog";
import { ReportDialog } from "./ReportDialog";
import { UpdateDialog } from "./UpdateDialog";
import { UploadSheet } from "./UploadSheet";
import { Wordmark } from "./Wordmark";

interface Destination {
  to: string;
  label: string;
  icon: LucideIcon;
  matches: string[];
}

const DESTINATIONS: Destination[] = [
  { to: "/", label: "Monitors", icon: ScanEye, matches: ["", "monitors"] },
  { to: "/prints", label: "Prints", icon: Layers, matches: ["prints"] },
  { to: "/cameras", label: "Cameras", icon: Camera, matches: ["cameras"] },
  { to: "/printers", label: "Printers", icon: Printer, matches: ["printers"] },
  { to: "/settings", label: "Settings", icon: Settings, matches: ["settings"] },
];

function useSection(): string {
  return useLocation().pathname.split("/")[1];
}

function TopNav() {
  const section = useSection();
  const update = useStore((s) => s.engine?.update?.available ?? false);
  return (
    <nav aria-label="Primary" className="topbar-nav">
      {DESTINATIONS.map(({ to, label, matches }, index) => (
        <Link key={to} to={to} className="topbar-tab" aria-current={matches.includes(section) ? "page" : undefined}>
          <span aria-hidden className="topbar-index">
            {String(index + 1).padStart(2, "0")}
          </span>
          {label}
          {to === "/settings" && update && (
            <>
              <span aria-hidden className="size-2 bg-accent lg:hidden" />
              <span className="sr-only lg:hidden">, update available</span>
            </>
          )}
        </Link>
      ))}
    </nav>
  );
}

function Dock() {
  const section = useSection();
  const update = useStore((s) => s.engine?.update?.available ?? false);
  return (
    <nav aria-label="Primary" className="dock">
      {DESTINATIONS.map(({ to, label, icon: Icon, matches }) => (
        <Link key={to} to={to} className="dock-item" aria-current={matches.includes(section) ? "page" : undefined}>
          <span className="relative">
            <Icon size={20} aria-hidden />
            {to === "/settings" && update && <span className="dock-badge" />}
          </span>
          {label}
          {to === "/settings" && update && <span className="sr-only">, update available</span>}
        </Link>
      ))}
    </nav>
  );
}

function Readouts() {
  const stats = useStore((s) => s.engine?.stats);
  if (!stats) return null;
  return (
    <div className="topbar-readouts">
      <Link to="/settings/detection" className="topbar-readout topbar-compute" aria-label={`Compute: ${stats.inference_device}. Choose the detection model and runtime`}>
        <span>{stats.inference_device.toLowerCase()}</span>
        <span className="label">Compute</span>
      </Link>
      <div className="topbar-readout">
        <span>{stats.capacity_fps.toFixed(1)} fps</span>
        <span className="label">Capacity</span>
      </div>
      <div className="topbar-readout">
        <span>{stats.infer_ms.toFixed(0)} ms</span>
        <span className="label">Latency</span>
      </div>
    </div>
  );
}

function VersionCell() {
  const version = useStore((s) => s.engine?.version);
  const update = useStore((s) => s.engine?.update);
  const openDialog = useStore((s) => s.openDialog);
  if (!version) return null;
  const available = update?.available;
  return (
    <button
      className={`topbar-cell max-lg:hidden ${available ? "text-accent" : ""}`}
      title={available ? `Update available: v${update!.latest}` : `PrintGuard v${version}`}
      onClick={() => openDialog("update")}
    >
      {available ? `Update v${update!.latest}` : `v${version}`}
    </button>
  );
}

function ThemeCell() {
  const theme = useStore((s) => s.engine?.settings.theme ?? "system");
  const themes = useStore((s) => s.engine?.settings.themes ?? []);
  const stored = useStore((s) => s.engine?.settings.glass);
  const updateSettings = useStore((s) => s.updateSettings);
  const custom = themes.find((t) => t.id === theme);
  const name = custom ? custom.name : theme === GLASS ? "Glass" : theme === "system" ? "System" : theme === "light" ? "Light" : "Dark";
  return (
    <>
      <button
        className="topbar-cell tuner-anchor max-w-40 max-lg:hidden"
        aria-label={`Theme: ${name}. Switch theme`}
        onClick={() => {
          const next = nextScheme(theme);
          applyTheme(next, themes, stored);
          updateSettings({ theme: next });
          if (next === GLASS) document.getElementById(GLASS_TUNER)?.showPopover?.();
        }}
      >
        <span className="truncate">{name}</span>
      </button>
      <GlassTuner />
    </>
  );
}

function TopBar() {
  const reconnecting = useStore((s) => s.reconnecting);
  const openDialog = useStore((s) => s.openDialog);
  return (
    <header className="topbar">
      <Link to="/" className="topbar-brand">
        <Wordmark size="text-base" />
      </Link>
      <TopNav />
      <span role="status" className="topbar-status">
        {reconnecting && <span className="boot-cursor truncate px-4">Reconnecting</span>}
      </span>
      <Readouts />
      <VersionCell />
      <ThemeCell />
      <button className="topbar-cell topbar-icon" aria-label="Open the guide" title="Guide" onClick={() => openDialog("guide")}>
        <CircleHelp size={18} aria-hidden />
      </button>
      <button className="topbar-cell topbar-icon" aria-label="Report a bug" title="Report a bug" onClick={() => openDialog("report")}>
        <Bug size={18} aria-hidden />
      </button>
      <button className="topbar-add" aria-label="Add monitor" onClick={() => openDialog("monitor")}>
        + Add
      </button>
    </header>
  );
}

function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const ref = useRef<HTMLDivElement>(null);
  const prevLen = useRef(0);
  const modal = useTopModal();

  useEffect(() => {
    const topLayer = ref.current;
    if (!topLayer || typeof topLayer.showPopover !== "function") return;
    const grew = toasts.length > prevLen.current;
    prevLen.current = toasts.length;
    const restackAboveDialogs = () => {
      if (topLayer.matches(":popover-open")) topLayer.hidePopover();
      topLayer.showPopover();
    };
    if (toasts.length === 0) {
      if (topLayer.matches(":popover-open")) topLayer.hidePopover();
    } else if (grew || !topLayer.matches(":popover-open")) restackAboveDialogs();
  }, [toasts.length, modal]);

  const layer = (
    <div ref={ref} popover="manual" className="toasts" data-over-modal={modal ? "" : undefined}>
      {toasts.map((toast) => (
        <div key={toast.id} role={toast.kind === "alert" ? "alert" : "status"} className="toast rise-in" data-kind={toast.kind}>
          {toast.text}
        </div>
      ))}
    </div>
  );
  return modal ? createPortal(layer, modal) : layer;
}

function useFocusOnNavigate() {
  const { pathname } = useLocation();
  const leavePage = useStore((s) => s.leavePage);
  const section = pathname.split("/")[1];
  const shown = useRef({ pathname, section });

  useLayoutEffect(() => {
    if (shown.current.pathname === pathname) return;
    const sectionChanged = shown.current.section !== section;
    shown.current = { pathname, section };
    leavePage(sectionChanged);
    if (sectionChanged) window.scrollTo(0, 0);
    const main = document.getElementById("main");
    const focused = document.activeElement as HTMLElement | null;
    if (focused && main?.contains(focused) && focused.checkVisibility()) return;
    const headings = [...(main?.querySelectorAll<HTMLElement>(sectionChanged ? "h1" : "h1, [data-heading]") ?? [])].filter((heading) => heading.checkVisibility());
    headings.at(-1)?.focus({ preventScroll: true });
  }, [pathname, section, leavePage]);
}

export function Shell() {
  const dialog = useStore((s) => s.dialog);
  const staged = useStore((s) => s.staged);
  const background = useStore((s) => s.background);
  useFocusOnNavigate();
  return (
    <div
      className="app"
      data-painted={background ? "" : undefined}
      style={background ? ({ "--painted-image": `url("${background.image}")` } as React.CSSProperties) : undefined}
    >
      <a
        href="#main"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <TopBar />
      <main id="main" tabIndex={-1} className="app-main">
        <Outlet />
      </main>
      <Dock />
      {dialog === "monitor" && <MonitorDialog />}
      {dialog === "update" && <UpdateDialog />}
      {dialog === "guide" && <GuideDialog />}
      {dialog === "intro" && <IntroDialog />}
      {dialog === "report" && <ReportDialog />}
      {staged.length > 0 && <UploadSheet />}
      <Toasts />
    </div>
  );
}
