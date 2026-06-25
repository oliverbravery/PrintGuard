import { useEffect, useRef, useState } from "react";
import { listVideoInputs } from "../media";
import { useStore } from "../store";
import type { Camera, CameraSource } from "../types";
import { publishStream, published, stopPublishing } from "../stream";
import { sourceLabel } from "./CameraRail";
import { CropEditor } from "./CropEditor";
import { Dialog } from "./Dialog";
import { SaveStatus } from "./SaveStatus";

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "camera";
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <div className="flex justify-between mb-1">
        <span className="label">{label}</span>
        <span className="mono text-[0.68rem] text-text-0">{value.toFixed(2)}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function CameraRow({ camera, focus }: { camera: Camera; focus: boolean }) {
  const { engine, send, isPending, updateCamera } = useStore();
  const [open, setOpen] = useState(focus);
  const ref = useRef<HTMLDivElement>(null);
  const owner = camera.printer_id ? engine?.printers.find((p) => p.id === camera.printer_id) : null;

  useEffect(() => {
    if (focus) {
      setOpen(true);
      ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focus]);

  return (
    <div ref={ref} className="panel overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2">
        <span className={`led ${camera.online ? "led-on" : "led-off"}`} />
        <div className="flex-1 min-w-0 leading-tight">
          <div className="text-sm font-medium truncate">{camera.name}</div>
          <div className="mono text-[0.62rem] text-text-2 truncate">{sourceLabel(camera.source)}</div>
        </div>
        <span className="mono text-[0.68rem] text-text-1">{camera.max_fps.toFixed(0)} fps</span>
        {camera.source.path && published.has(camera.source.path) && (
          <span className="chip chip-accent">publishing</span>
        )}
        {owner && <span className="chip" title="Managed by its printer integration — remove the printer to remove this camera">via {owner.name}</span>}
        <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide" : "Adjust"}
        </button>
        {!owner && (
          <button
            className="btn btn-danger !py-1 !px-2.5 !text-[0.62rem]"
            disabled={isPending("camera.remove")}
            onClick={() => {
              if (camera.source.path) stopPublishing(camera.source.path);
              send({ cmd: "camera.remove", id: camera.id });
            }}
          >
            {isPending("camera.remove") ? "Removing…" : "Remove"}
          </button>
        )}
      </div>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-line-0 space-y-3">
          <Slider
            label="Brightness"
            value={camera.brightness ?? 1}
            min={0.25}
            max={2}
            step={0.05}
            onChange={(v) => updateCamera(camera.id, { brightness: v })}
          />
          <Slider
            label="Contrast"
            value={camera.contrast ?? 1}
            min={0.25}
            max={2}
            step={0.05}
            onChange={(v) => updateCamera(camera.id, { contrast: v })}
          />
          <Slider
            label="Sharpness"
            value={camera.sharpness ?? 0}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => updateCamera(camera.id, { sharpness: v })}
          />
          <div className="space-y-1.5">
            <span className="label">Rotation</span>
            <div className="flex gap-1.5">
              {[0, 90, 180, 270].map((deg) => (
                <button
                  key={deg}
                  className={`btn flex-1 !py-1.5 !text-[0.66rem] ${(camera.rotation ?? 0) === deg ? "!border-accent !text-accent" : ""}`}
                  onClick={() => updateCamera(camera.id, { rotation: deg })}
                >
                  {deg}°
                </button>
              ))}
            </div>
          </div>
          <CropEditor
            camera={camera}
            mode={engine?.mode ?? "local"}
            crop={camera.crop ?? null}
            rotation={camera.rotation ?? 0}
            onChange={(crop) => updateCamera(camera.id, { crop })}
          />
          <div className="flex justify-end pt-1">
            <SaveStatus />
          </div>
        </div>
      )}
    </div>
  );
}

function CameraList({ cameras }: { cameras: Camera[] }) {
  const { focusCameraId } = useStore();
  if (!cameras.length) return null;
  return (
    <div className="space-y-2 mb-6">
      {cameras.map((camera) => (
        <CameraRow key={camera.id} camera={camera} focus={camera.id === focusCameraId} />
      ))}
    </div>
  );
}

function PrinterCameras() {
  const { engine, send, isPending } = useStore();
  const cameras = (engine?.cameras ?? []).filter((c) => c.printer_id);
  const hasPrinters = (engine?.printers ?? []).length > 0;
  const busy = isPending("printer.cameras.refresh");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <p className="flex-1 text-xs text-text-1">
          Cameras connected to your registered printers. Refresh to register any added since.
        </p>
        <button
          className="btn btn-primary !py-1.5"
          disabled={!hasPrinters || busy}
          onClick={() => send({ cmd: "printer.cameras.refresh" })}
        >
          {busy ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {!hasPrinters && <p className="mono text-[0.7rem] text-text-2">register a printer first</p>}
      {hasPrinters && !cameras.length && (
        <p className="mono text-[0.7rem] text-text-2">no printer cameras found — refresh after connecting one</p>
      )}
      <CameraList cameras={cameras} />
    </div>
  );
}

function DevicePicker({ onAdd }: { onAdd: (name: string, source: CameraSource) => void }) {
  const { discovered, discovering, discover, isPending } = useStore();
  const busy = isPending("camera.add");
  const [name, setName] = useState("");
  const [deviceId, setDeviceId] = useState("");
  useEffect(() => {
    discover();
  }, []);
  const devices = (discovered ?? []).filter((s) => s.kind === "device");
  return (
    <div className="space-y-3">
      {discovering && <p className="mono text-[0.7rem] text-text-2 boot-cursor">scanning devices</p>}
      {!discovering && !devices.length && <p className="mono text-[0.7rem] text-text-2">no unregistered cameras found</p>}
      {devices.length > 0 && (
        <select className="field" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
          <option value="">Select a camera…</option>
          {devices.map((d) => (
            <option key={d.device_id} value={d.device_id}>
              {d.label}
            </option>
          ))}
        </select>
      )}
      <input className="field" placeholder="Name (e.g. Ender 3 nozzle cam)" value={name} onChange={(e) => setName(e.target.value)} />
      <button
        className="btn btn-primary w-full"
        disabled={!deviceId || busy}
        onClick={() => {
          const device = devices.find((d) => d.device_id === deviceId)!;
          onAdd(name || device.label || "Camera", { kind: "device", device_id: deviceId, label: device.label });
        }}
      >
        {busy ? "Measuring fps…" : "Register camera"}
      </button>
    </div>
  );
}

function HubAdd({ onDone }: { onDone: () => void }) {
  const { send, toast, discovered, discovering, discover, isPending } = useStore();
  const [tab, setTab] = useState<"url" | "publish" | "paths">("url");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (tab === "paths") discover();
    if (tab === "publish") {
      listVideoInputs()
        .then(setDevices)
        .catch((err) => toast("error", `camera access: ${err instanceof Error ? err.message : err}`));
    }
  }, [tab]);

  const publish = async () => {
    setBusy(true);
    try {
      const path = `dev-${slug(name || "camera")}`;
      const { hlsPlayable } = await publishStream(path, deviceId, (reason) =>
        toast("error", `publishing stopped: ${reason}`),
      );
      if (!hlsPlayable) {
        toast("alert", "this browser records VP8 — monitoring works and you can preview it here, but other devices can't view this camera");
      }
      await new Promise((r) => setTimeout(r, 800));
      send({ cmd: "camera.add", name: name || "Published camera", source: { kind: "path", path } });
      onDone();
    } catch (err) {
      toast("error", `publish failed: ${err}`);
    } finally {
      setBusy(false);
    }
  };

  const tabs: Array<["url" | "publish" | "paths", string]> = [
    ["url", "Stream URL"],
    ["publish", "This device"],
    ["paths", "Discovered"],
  ];
  return (
    <div>
      <div className="flex gap-1.5 mb-4">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={`btn !py-1.5 !px-3 !text-[0.66rem] ${tab === key ? "!border-accent !text-accent" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "url" && (
        <div className="space-y-3">
          <input className="field" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <input
            className="field"
            placeholder="rtsp:// rtmp:// or http:// stream URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button
            className="btn btn-primary w-full"
            disabled={!url.trim() || isPending("camera.add")}
            onClick={() => {
              send({ cmd: "camera.add", name: name || "Stream", source: { kind: "url", url: url.trim() } });
              onDone();
            }}
          >
            {isPending("camera.add") ? "Registering…" : "Register stream"}
          </button>
        </div>
      )}
      {tab === "publish" && (
        <div className="space-y-3">
          <p className="text-xs text-text-1">
            Streams this device's camera to the hub. It reconnects if the hub restarts and resumes
            when you reopen this page on this device.
          </p>
          <select className="field" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
            <option value="">Select a camera…</option>
            {devices.map((d, i) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || `Camera ${i + 1}`}
              </option>
            ))}
          </select>
          <input className="field" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-primary w-full" disabled={!deviceId || busy || isPending("camera.add")} onClick={publish}>
            {busy ? "Publishing…" : isPending("camera.add") ? "Registering…" : "Publish & register"}
          </button>
        </div>
      )}
      {tab === "paths" && (
        <div className="space-y-2">
          {discovering && <p className="mono text-[0.7rem] text-text-2 boot-cursor">querying mediamtx</p>}
          {!discovering && !(discovered ?? []).length && (
            <p className="mono text-[0.7rem] text-text-2">no unregistered streams on the hub</p>
          )}
          {(discovered ?? []).map((s) => (
            <div key={s.path} className="flex items-center gap-3 panel px-3 py-2">
              <span className="mono text-[0.72rem] flex-1 truncate">{s.path}</span>
              <button
                className="btn !py-1 !px-2.5 !text-[0.62rem]"
                disabled={isPending("camera.add")}
                onClick={() => {
                  send({ cmd: "camera.add", name: s.path!, source: { kind: "path", path: s.path } });
                  onDone();
                }}
              >
                {isPending("camera.add") ? "Registering…" : "Register"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CamerasDialog() {
  const { engine, send, openDialog, focusCameraId } = useStore();
  const close = () => openDialog(null);
  const isLocal = engine?.mode === "local";
  const cameras = engine?.cameras ?? [];
  const focusIsPrinter = cameras.some((c) => c.id === focusCameraId && c.printer_id);
  const [tab, setTab] = useState<"cameras" | "printers">(focusIsPrinter ? "printers" : "cameras");
  const tabs: Array<["cameras" | "printers", string]> = [
    ["cameras", "Cameras"],
    ["printers", "Printer cameras"],
  ];
  return (
    <Dialog title="Camera registry" onClose={close}>
      <div className="flex gap-1.5 mb-4">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={`btn !py-1.5 !px-3 !text-[0.66rem] ${tab === key ? "!border-accent !text-accent" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "cameras" ? (
        <>
          <CameraList cameras={cameras.filter((c) => !c.printer_id)} />
          <div className="label mb-3">Register new</div>
          {isLocal ? (
            <DevicePicker onAdd={(name, source) => send({ cmd: "camera.add", name, source })} />
          ) : (
            <HubAdd onDone={() => {}} />
          )}
        </>
      ) : (
        <PrinterCameras />
      )}
    </Dialog>
  );
}
