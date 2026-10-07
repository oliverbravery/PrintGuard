import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { applyLayout, section, tiles, withOrder } from "../layout";
import { useStore } from "../store";
import { CameraRail } from "./CameraRail";
import { CamerasDialog } from "./CamerasDialog";
import { CustomiseBar } from "./CustomiseBar";
import { DetailPanel } from "./DetailPanel";
import { useTopModal } from "./Dialog";
import { GettingStarted } from "./GettingStarted";
import { GuideDialog } from "./GuideDialog";
import { IntroDialog } from "./IntroDialog";
import { Header } from "./Header";
import { MonitorDialog } from "./MonitorDialog";
import { MonitorTile } from "./MonitorTile";
import { MoreSheet } from "./MoreSheet";
import { AppNav } from "./Nav";
import { PluginPanel } from "./PluginPanel";
import { PrintersDialog } from "./PrintersDialog";
import { PrintsDialog } from "./PrintsDialog";
import { PrintViewer } from "./PrintViewer";
import { ReportDialog } from "./ReportDialog";
import { SettingsDialog } from "./SettingsDialog";
import { rectSortingStrategy, Sortable } from "./Sortable";
import { ReviewSheet } from "./ReviewSheet";
import { StatsPage } from "./StatsPage";
import { UpdateDialog } from "./UpdateDialog";
import { UploadSheet } from "./UploadSheet";

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
    <div
      ref={ref}
      popover="manual"
      aria-label="Notifications"
      className={`fixed inset-auto right-4 bottom-4 z-50 m-0 w-fit max-w-sm space-y-2 border-0 bg-transparent p-0 text-text-0 max-sm:left-4 max-sm:max-w-[calc(100vw-2rem)] ${
        modal ? "max-sm:top-[calc(0.75rem+env(safe-area-inset-top))] max-sm:bottom-auto" : "max-sm:bottom-[calc(5rem+env(safe-area-inset-bottom))]"
      }`}
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role={toast.kind === "alert" ? "alert" : "status"}
          className={`panel rise-in px-4 py-2.5 text-sm break-words border-l-2 ${
            toast.kind === "alert" ? "!border-l-bad text-bad" : toast.kind === "error" ? "!border-l-warn" : "!border-l-accent"
          }`}
        >
          {toast.text}
        </div>
      ))}
    </div>
  );
  return modal ? createPortal(layer, modal) : layer;
}

export function Dashboard() {
  const { engine, dialog, detailId, statsMonitorId, reviewId, printId, staged, customising, setCustomising, mutateLayout, background } = useStore();
  const monitors = engine?.monitors ?? [];
  const tileLayout = section(engine?.settings.layout, "monitors");
  const { visible, hidden } = applyLayout(tiles(engine), tileLayout);
  const detail = monitors.find((m) => m.id === detailId);
  const stats = monitors.find((m) => m.id === statsMonitorId);
  const review = engine?.reviews.find((r) => r.id === reviewId);
  const reviewed = monitors.find((m) => m.id === review?.monitor_id);
  const print = engine?.prints.find((p) => p.id === printId);
  return (
    <div
      className="app min-h-dvh"
      data-painted={background ? "" : undefined}
      style={background ? ({ "--painted-image": `url("${background.image}")` } as React.CSSProperties) : undefined}
    >
      <a href="#main" className="skip-link">
        Skip to monitors
      </a>
      <Header />
      <CustomiseBar />
      <CameraRail />
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto max-w-[1500px] px-4 py-5 sm:px-6"
      >
        {monitors.length === 0 && <GettingStarted />}
        {visible.length === 0 && hidden.length > 0 && !customising && (
          <div className="plate flex flex-wrap items-center gap-3 py-2">
            <p className="mono text-[0.7rem] text-text-2">
              {hidden.length} {hidden.length === 1 ? "monitor" : "monitors"} hidden
            </p>
            <button className="btn !py-1.5 !px-3 !text-[0.68rem]" onClick={() => setCustomising(true)}>
              Customise
            </button>
          </div>
        )}
        {visible.length > 0 && (
          <Sortable
            ids={visible.map((m) => m.id)}
            pinned={tileLayout.pinned}
            strategy={rectSortingStrategy}
            disabled={!customising}
            onReorder={(ids) => mutateLayout("monitors", (s) => withOrder(s, ids))}
          >
            <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr))]">
              {visible.map((tile, index) =>
                tile.monitor ? (
                  <MonitorTile key={tile.id} monitor={tile.monitor} index={index} />
                ) : (
                  <PluginPanel key={tile.id} plugin={tile.plugin!} />
                ),
              )}
            </div>
          </Sortable>
        )}
      </main>
      {dialog === "cameras" && <CamerasDialog />}
      {dialog === "printers" && <PrintersDialog />}
      {dialog === "prints" && <PrintsDialog />}
      {dialog === "monitor" && <MonitorDialog />}
      {dialog === "settings" && <SettingsDialog />}
      {dialog === "update" && <UpdateDialog />}
      {dialog === "guide" && <GuideDialog />}
      {dialog === "intro" && <IntroDialog />}
      {dialog === "report" && <ReportDialog />}
      {dialog === "more" && <MoreSheet />}
      {detail && <DetailPanel monitor={detail} />}
      {stats && <StatsPage monitor={stats} />}
      {review && reviewed && <ReviewSheet key={review.id} review={review} monitor={reviewed} />}
      {print && <PrintViewer print={print} />}
      {staged.length > 0 && <UploadSheet />}
      <Toasts />
      <AppNav />
    </div>
  );
}
