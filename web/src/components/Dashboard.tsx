import { useStore } from "../store";
import { CameraRail } from "./CameraRail";
import { CamerasDialog } from "./CamerasDialog";
import { DetailPanel } from "./DetailPanel";
import { Header, MobileActionBar } from "./Header";
import { MonitorDialog } from "./MonitorDialog";
import { MonitorTile } from "./MonitorTile";
import { PrintersDialog } from "./PrintersDialog";
import { SettingsDialog } from "./SettingsDialog";

function EmptyState() {
  const openDialog = useStore((s) => s.openDialog);
  return (
    <div className="reveal grid place-items-center py-24 text-center">
      <div className="relative p-12">
        <span className="corner corner-tl !border-text-2" />
        <span className="corner corner-tr !border-text-2" />
        <span className="corner corner-bl !border-text-2" />
        <span className="corner corner-br !border-text-2" />
        <div className="led led-infer mx-auto mb-6" />
        <h2 className="display text-2xl font-bold mb-2">NO MONITORS ON WATCH</h2>
        <p className="text-sm text-text-1 max-w-sm mx-auto mb-7">
          Register a camera, register your printer, then add a monitor to bind them — PrintGuard
          shares inference fairly across everything it watches.
        </p>
        <div className="flex flex-wrap gap-3 justify-center">
          <button className="btn" onClick={() => openDialog("cameras")}>
            1 · Register camera
          </button>
          <button className="btn" onClick={() => openDialog("printers")}>
            2 · Register printer
          </button>
          <button className="btn btn-primary" onClick={() => openDialog("monitor")}>
            3 · Add monitor
          </button>
        </div>
      </div>
    </div>
  );
}

function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="fixed right-4 bottom-4 z-50 space-y-2 max-w-sm max-md:left-4 max-md:bottom-[calc(4.75rem+env(safe-area-inset-bottom))]">
      {toasts.map((toast) => (
        <div
          key={toast.id}
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
  const { engine, dialog, detailId } = useStore();
  const monitors = engine?.monitors ?? [];
  const detail = monitors.find((m) => m.id === detailId);
  return (
    <div className="min-h-screen">
      <Header />
      <CameraRail />
      <main className="mx-auto max-w-[1500px] px-4 sm:px-6 py-5 max-md:pb-[calc(5rem+env(safe-area-inset-bottom))]">
        {monitors.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr))]">
            {monitors.map((monitor, index) => (
              <MonitorTile key={monitor.id} monitor={monitor} index={index} />
            ))}
          </div>
        )}
      </main>
      {dialog === "cameras" && <CamerasDialog />}
      {dialog === "printers" && <PrintersDialog />}
      {dialog === "monitor" && <MonitorDialog />}
      {dialog === "settings" && <SettingsDialog />}
      {detail && <DetailPanel monitor={detail} />}
      <Toasts />
      <MobileActionBar />
    </div>
  );
}
