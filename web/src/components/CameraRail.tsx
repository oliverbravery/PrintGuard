import { useStore } from "../store";
import type { Camera, CameraSource } from "../types";

export function sourceLabel(source: CameraSource): string {
  if (source.kind === "device") return source.label || "device camera";
  if (source.kind === "path") return `path://${source.path}`;
  return source.url ?? source.kind;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="leading-tight">
      <div className="mono text-[0.72rem] text-text-0">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function CameraCard({ camera }: { camera: Camera }) {
  return (
    <div className="panel flex items-center gap-4 px-3.5 py-2.5 flex-none">
      <span
        className={`led ${camera.inferring ? "led-infer" : camera.online ? "led-on" : "led-off"}`}
        title={camera.online ? "online" : "offline"}
      />
      <div className="leading-tight min-w-0">
        <div className="display text-sm font-semibold truncate max-w-36">{camera.name}</div>
        <div className="mono text-[0.6rem] text-text-2 truncate max-w-36">{sourceLabel(camera.source)}</div>
      </div>
      <Stat label="max" value={`${camera.max_fps.toFixed(0)}`} />
      <Stat label="target" value={camera.in_use ? camera.target_fps.toFixed(1) : "—"} />
      <Stat label="actual" value={camera.in_use ? camera.achieved_fps.toFixed(1) : "—"} />
      <span className={`chip ${camera.in_use ? "chip-accent" : ""}`}>{camera.in_use ? "in use" : "idle"}</span>
    </div>
  );
}

export function CameraRail() {
  const { engine, openDialog } = useStore();
  const cameras = engine?.cameras ?? [];
  return (
    <section className="mx-auto max-w-[1500px] px-4 sm:px-6 pt-5">
      <div className="flex items-center gap-3 mb-2.5">
        <h2 className="display text-xs font-semibold tracking-[0.24em] text-text-2">CAMERA REGISTRY</h2>
        <div className="hairline flex-1" />
        <button className="btn !py-1.5 !px-3 !text-[0.68rem]" onClick={() => openDialog("cameras")}>
          + Camera
        </button>
      </div>
      {cameras.length === 0 ? (
        <p className="mono text-[0.7rem] text-text-2 py-1.5">no cameras registered</p>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-1.5">
          {cameras.map((camera) => (
            <CameraCard key={camera.id} camera={camera} />
          ))}
        </div>
      )}
    </section>
  );
}
