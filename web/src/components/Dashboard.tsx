import { useEffect, useRef } from "react";
import { applyLayout, section, withOrder } from "../layout";
import { useStore } from "../store";
import { CameraRail } from "./CameraRail";
import { CamerasDialog } from "./CamerasDialog";
import { CustomiseBar } from "./CustomiseBar";
import { DetailPanel } from "./DetailPanel";
import { GettingStarted } from "./GettingStarted";
import { GuideDialog } from "./GuideDialog";
import { Header, MobileActionBar } from "./Header";
import { MonitorDialog } from "./MonitorDialog";
import { MonitorTile } from "./MonitorTile";
import { PrintersDialog } from "./PrintersDialog";
import { SettingsDialog } from "./SettingsDialog";
import { rectSortingStrategy, Sortable } from "./Sortable";
import { StatsPage } from "./StatsPage";
import { UpdateDialog } from "./UpdateDialog";

function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const ref = useRef<HTMLDivElement>(null);
  const prevLen = useRef(0);

  // Promote the toast layer into the top layer so defect alerts stay visible above an open
  // <dialog>; re-show on each new toast to re-stack above a dialog opened after it.
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof el.showPopover !== "function") return;
    const grew = toasts.length > prevLen.current;
    prevLen.current = toasts.length;
    if (toasts.length === 0) {
      if (el.matches(":popover-open")) el.hidePopover();
    } else if (grew || !el.matches(":popover-open")) {
      if (el.matches(":popover-open")) el.hidePopover();
      el.showPopover();
    }
  }, [toasts.length]);

  return (
    <div
      ref={ref}
      popover="manual"
      aria-label="Notifications"
      className="fixed inset-auto right-4 bottom-4 z-50 m-0 w-fit max-w-sm space-y-2 border-0 bg-transparent p-0 max-md:left-4 max-md:bottom-[calc(4.75rem+env(safe-area-inset-bottom))]"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role={toast.kind === "alert" ? "alert" : "status"}
          className={`panel rise-in px-4 py-2.5 text-sm border-l-2 ${
            toast.kind === "alert" ? "!border-l-bad text-bad" : toast.kind === "error" ? "!border-l-warn" : "!border-l-accent"
          }`}
        >
          {toast.text}
        </div>
      ))}
    </div>
  );
}

export function Dashboard() {
  const { engine, dialog, detailId, statsMonitorId, customising, mutateLayout } = useStore();
  const monitors = engine?.monitors ?? [];
  const { visible } = applyLayout(monitors, section(engine?.settings.layout, "monitors"));
  const detail = monitors.find((m) => m.id === detailId);
  const stats = monitors.find((m) => m.id === statsMonitorId);
  return (
    <div className="min-h-screen">
      <a href="#main" className="skip-link">
        Skip to monitors
      </a>
      <Header />
      <CustomiseBar />
      <CameraRail />
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto max-w-[1500px] px-4 sm:px-6 py-5 max-md:pb-[calc(5rem+env(safe-area-inset-bottom))]"
      >
        {monitors.length === 0 ? (
          <GettingStarted />
        ) : (
          <Sortable
            ids={visible.map((m) => m.id)}
            strategy={rectSortingStrategy}
            disabled={!customising}
            onReorder={(ids) => mutateLayout("monitors", (s) => withOrder(s, ids))}
          >
            <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr))]">
              {visible.map((monitor, index) => (
                <MonitorTile key={monitor.id} monitor={monitor} index={index} />
              ))}
            </div>
          </Sortable>
        )}
      </main>
      {dialog === "cameras" && <CamerasDialog />}
      {dialog === "printers" && <PrintersDialog />}
      {dialog === "monitor" && <MonitorDialog />}
      {dialog === "settings" && <SettingsDialog />}
      {dialog === "update" && <UpdateDialog />}
      {dialog === "guide" && <GuideDialog />}
      {detail && <DetailPanel monitor={detail} />}
      {stats && <StatsPage monitor={stats} />}
      <Toasts />
      <MobileActionBar />
    </div>
  );
}
