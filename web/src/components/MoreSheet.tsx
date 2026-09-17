import { ArrowUpCircle, Bug, CircleHelp, FlaskConical, LayoutGrid, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useStore } from "../store";
import { Dialog } from "./Dialog";
import { SchemePicker } from "./SchemePicker";

function Row({ icon: Icon, label, detail, onClick }: { icon: LucideIcon; label: string; detail?: ReactNode; onClick: () => void }) {
  return (
    <button
      className="flex w-full cursor-pointer items-center gap-3 rounded border border-line-0 bg-ink-0/40 px-3.5 py-3 text-left text-sm text-text-0 transition-colors hover:border-accent"
      onClick={onClick}
    >
      <Icon size={18} className="shrink-0 text-text-1" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {detail}
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line-0 bg-ink-0/40 px-3 py-2 leading-tight">
      <div className="mono truncate text-[0.8rem] text-text-0">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

export function MoreSheet() {
  const { engine, mode, openDialog, customising, setCustomising } = useStore();
  const stats = engine?.stats;
  const update = engine?.update;
  return (
    <Dialog title="More" onClose={() => openDialog(null)}>
      <div className="space-y-5">
        {stats && (
          <div className="grid grid-cols-3 gap-2">
            <Stat label="compute" value={stats.inference_device.toLowerCase()} />
            <Stat label="capacity" value={`${stats.capacity_fps.toFixed(1)} fps`} />
            <Stat label="latency" value={`${stats.infer_ms.toFixed(0)} ms`} />
          </div>
        )}
        <div className="space-y-2">
          <span className="label block">Theme</span>
          <SchemePicker />
        </div>
        <div className="space-y-2">
          <Row
            icon={LayoutGrid}
            label={customising ? "Stop customising" : "Customise layout"}
            onClick={() => {
              setCustomising(!customising);
              openDialog(null);
            }}
          />
          <Row icon={CircleHelp} label="Guide" onClick={() => openDialog("guide")} />
          <Row icon={Bug} label="Report a bug" onClick={() => openDialog("report")} />
          {engine?.version && (
            <Row
              icon={ArrowUpCircle}
              label={update?.available ? `Update to v${update.latest}` : `PrintGuard v${engine.version}`}
              detail={update?.available ? <span className="chip chip-accent">new</span> : undefined}
              onClick={() => openDialog("update")}
            />
          )}
          {mode === "local" && <Row icon={FlaskConical} label="About the live demo" onClick={() => openDialog("demo")} />}
        </div>
      </div>
    </Dialog>
  );
}
