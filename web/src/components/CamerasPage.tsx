import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { listVideoInputs } from "../media";
import { useStore } from "../store";
import type { Camera, CameraSource } from "../types";
import { publishStream, published } from "../stream";
import { cameraStatus, sourceLabel } from "../cameras";
import { ConfirmButton } from "./ConfirmButton";
import { CropEditor } from "./CropEditor";
import { Feed, useCovered } from "./Feed";
import { NameField } from "./NameField";
import { SaveStatus } from "./SaveStatus";
import { Slider } from "./Slider";
import { DetailHead, Page, Split } from "./Page";
import { Segmented } from "./Segmented";
import { Status } from "./Status";
import { TabPanel, Tabs } from "./Tabs";

const UNCAPPED_DETECT_FPS = 60;

function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "camera";
}

function useRegistered(onRegistered: () => void) {
  const { engine, isPending } = useStore();
  const registering = isPending("camera.add");
  const cameras = engine?.cameras.length ?? 0;
  const camerasWhenSent = useRef(cameras);
  useEffect(() => {
    if (registering) camerasWhenSent.current = cameras;
    else if (cameras > camerasWhenSent.current) onRegistered();
  }, [registering]);
}

function CameraEditor({ camera }: { camera: Camera }) {
  const { engine, send, isPending, updateCamera } = useStore();
  const owner = camera.printer_id ? engine?.printers.find((p) => p.id === camera.printer_id) : null;
  const managed = Boolean(owner) || Boolean(camera.declared);
  const removalHint = owner
    ? "Managed by its printer integration, remove the printer to remove this camera."
    : camera.declared
      ? "Passed in by the deployment, remove its devices entry to remove this camera."
      : null;
  const detectFpsCeiling = Math.min(UNCAPPED_DETECT_FPS, Math.ceil(camera.max_fps));
  const covered = useCovered();
  return (
    <>
      <DetailHead title={camera.name}>
        <SaveStatus scope={`camera:${camera.id}`} />
        {!managed && (
          <ConfirmButton
            disabled={isPending("camera.remove", camera.id)}
            onConfirm={() => send({ cmd: "camera.remove", id: camera.id })}
          >
            {isPending("camera.remove", camera.id) ? "Removing…" : "Remove"}
          </ConfirmButton>
        )}
      </DetailHead>
      <div className="grid xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="min-w-0 border-b border-line-0 xl:border-r">
          <Feed camera={camera} active={!covered} />
          <div className="mono flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line-0 px-4 py-2 text-xs">
            <Status tone={camera.online ? "ok" : camera.standby ? "idle" : "bad"}>{cameraStatus(camera)}</Status>
            <span className="min-w-0 truncate text-text-1">{sourceLabel(camera.source)}</span>
            <span className="text-text-2">
              {camera.in_use ? `${camera.achieved_fps.toFixed(1)}/${camera.target_fps.toFixed(1)} fps · ` : "idle · "}
              {camera.max_fps.toFixed(0)} fps max
            </span>
            {camera.source.path && published.has(camera.source.path) && <span className="chip chip-accent">publishing</span>}
            {owner && <span className="chip">via {owner.name}</span>}
            {camera.declared && <span className="chip">passed in</span>}
          </div>
          {removalHint && <p className="border-t border-line-0 px-4 py-2 text-sm text-text-2">{removalHint}</p>}
        </div>
        <div className="min-w-0 space-y-5 border-b border-line-0 px-4 py-4">
          <NameField name={camera.name} onRename={(name) => updateCamera(camera.id, { name })} />
          <div className="grid gap-5 sm:grid-cols-2">
            <Slider label="Brightness" value={camera.brightness ?? 1} min={0.25} max={2} step={0.05} onChange={(v) => updateCamera(camera.id, { brightness: v })} />
            <Slider label="Contrast" value={camera.contrast ?? 1} min={0.25} max={2} step={0.05} onChange={(v) => updateCamera(camera.id, { contrast: v })} />
            <Slider
              label="Sharpness"
              value={camera.sharpness ?? 0}
              min={0}
              max={2}
              step={0.1}
              hint="The preview sharpens at the size it's drawn here, so it looks stronger than what the model gets."
              onChange={(v) => updateCamera(camera.id, { sharpness: v })}
            />
            <Slider
              label="Detection rate"
              value={Math.min(camera.detect_fps, detectFpsCeiling)}
              min={0.5}
              max={detectFpsCeiling}
              step={0.5}
              format={(v) => `${v} fps`}
              hint="Lower it to lighten the load on the hub. A defect then takes longer to confirm."
              onChange={(v) => updateCamera(camera.id, { detect_fps: v >= detectFpsCeiling ? UNCAPPED_DETECT_FPS : v })}
            />
          </div>
          <Segmented
            label="Rotation"
            options={[0, 90, 180, 270].map((deg) => ({ value: String(deg), label: `${deg}°` }))}
            value={String(camera.rotation ?? 0)}
            onChange={(deg) => updateCamera(camera.id, { rotation: Number(deg) })}
          />
        </div>
      </div>
      <div className="px-4 py-4">
        <CropEditor camera={camera} crop={camera.crop ?? null} rotation={camera.rotation ?? 0} onChange={(crop) => updateCamera(camera.id, { crop })} />
      </div>
    </>
  );
}

function CameraLink({ camera, selected }: { camera: Camera; selected: boolean }) {
  return (
    <Link to={`/cameras/${camera.id}`} aria-current={selected ? "page" : undefined} className="list-row">
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{camera.name}</span>
        <span className="mono block truncate text-xs text-text-2">{sourceLabel(camera.source)}</span>
        {camera.reason && <span className="block text-xs text-bad">{camera.reason}</span>}
      </span>
      <Status tone={camera.online ? "ok" : camera.standby ? "idle" : "bad"}>
        <span className="max-md:sr-only">{camera.online ? `${camera.achieved_fps.toFixed(1)} fps` : cameraStatus(camera)}</span>
      </Status>
    </Link>
  );
}

function DevicePicker({ onAdd, hint }: { onAdd: (name: string, source: CameraSource) => void; hint?: string }) {
  const { discovered, discovering, discover, isPending, reconnecting } = useStore();
  const busy = isPending("camera.add");
  const [name, setName] = useState("");
  const [deviceId, setDeviceId] = useState("");
  useEffect(() => {
    if (!reconnecting) discover();
  }, [reconnecting]);
  useRegistered(() => {
    setName("");
    setDeviceId("");
    discover();
  });
  const devices = (discovered ?? []).filter((s) => s.kind === "device");
  const register = () => {
    const device = devices.find((d) => d.device_id === deviceId)!;
    onAdd(name || device.label || "Camera", { kind: "device", device_id: deviceId, label: device.label });
  };
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        register();
      }}
    >
      {discovering && <p className="mono text-xs text-text-2 boot-cursor">scanning devices</p>}
      {discovered && !devices.length && (
        <>
          <p className="mono text-xs text-text-2">no unregistered cameras found</p>
          {hint && <p className="text-sm text-text-1">{hint}</p>}
        </>
      )}
      {devices.length > 0 && (
        <>
          <select className="field" aria-label="Camera" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
            <option value="">Select a camera…</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.label}
              </option>
            ))}
          </select>
          <input className="field" aria-label="Name" placeholder="Name (e.g. Ender 3 nozzle cam)" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-primary" type="submit" disabled={!deviceId || busy}>
            {busy ? "Measuring fps…" : "Register camera"}
          </button>
        </>
      )}
    </form>
  );
}

type AddTab = "url" | "machine" | "browser";

function AddCamera({ onDeviceAdd }: { onDeviceAdd: (name: string, source: CameraSource) => void }) {
  const { send, toast, isPending, addPublishedCamera } = useStore();
  const desktopApp = "pywebview" in window;
  const [tab, setTab] = useState<AddTab>("url");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(false);

  useRegistered(() => {
    setName("");
    setUrl("");
    setDeviceId("");
  });

  useEffect(() => {
    if (tab === "browser" && !desktopApp) {
      listVideoInputs()
        .then(setDevices)
        .catch((err) => toast("error", `camera access: ${err instanceof Error ? err.message : err}`));
    }
  }, [tab]);

  const publish = async () => {
    setBusy(true);
    try {
      const path = `dev-${slug(name || "camera")}-${Date.now().toString(36)}`;
      const { hlsPlayable } = await publishStream(path, deviceId, (reason) =>
        toast("error", `publishing stopped: ${reason}`),
      );
      if (!hlsPlayable) {
        toast("alert", "This browser records VP8, which the dashboard can't play, so this camera is monitored but has no live view. Chrome, Edge and Safari record H.264.");
      }
      await new Promise((r) => setTimeout(r, 800));
      addPublishedCamera(name || "Published camera", path);
    } catch (err) {
      toast("error", `publish failed: ${err}`);
    } finally {
      setBusy(false);
    }
  };

  const tabs: Array<[AddTab, string]> = [
    ["url", "Stream URL"],
    ["machine", "This machine"],
    ...(desktopApp ? [] : ([["browser", "This browser"]] as Array<[AddTab, string]>)),
  ];
  return (
    <div className="max-w-xl space-y-4 px-4 py-4">
      <Segmented label="Source" options={tabs.map(([value, label]) => ({ value, label }))} value={tab} onChange={setTab} />
      {tab === "url" && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            send({ cmd: "camera.add", name: name || "Stream", source: { kind: "url", url: url.trim() } });
          }}
        >
          <input className="field" aria-label="Name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <input
            className="field"
            aria-label="Stream URL"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder="rtsp:// rtmp:// http:// or whep:// stream URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button className="btn btn-primary" type="submit" disabled={!url.trim() || isPending("camera.add")}>
            {isPending("camera.add") ? "Registering…" : "Register stream"}
          </button>
        </form>
      )}
      {tab === "machine" && (
        <div className="space-y-3">
          <p className="text-sm text-text-1">
            Cameras plugged into the machine PrintGuard runs on. They register on the hub itself, so
            they keep watching with every window closed.
          </p>
          <DevicePicker
            onAdd={onDeviceAdd}
            hint={desktopApp ? undefined : "Pass each camera into the container with a devices: entry in your compose file."}
          />
        </div>
      )}
      {tab === "browser" && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void publish();
          }}
        >
          <p className="text-sm text-text-1">
            Streams this device's camera to the hub. It reconnects if the hub restarts and resumes
            when you reopen this page on this device.
          </p>
          <select className="field" aria-label="Camera" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
            <option value="">Select a camera…</option>
            {devices.map((d, i) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || `Camera ${i + 1}`}
              </option>
            ))}
          </select>
          <input className="field" aria-label="Name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn btn-primary" type="submit" disabled={!deviceId || busy || isPending("camera.add")}>
            {busy ? "Publishing…" : isPending("camera.add") ? "Registering…" : "Publish & register"}
          </button>
        </form>
      )}
    </div>
  );
}

type Group = "cameras" | "printers";

export function CamerasPage() {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const { engine, send, isPending } = useStore();
  const cameras = engine?.cameras ?? [];
  const adding = cameraId === "new";
  const chosen = cameras.find((camera) => camera.id === cameraId);
  const [group, setGroup] = useState<Group>(chosen?.printer_id ? "printers" : "cameras");
  const [registeredDevice, setRegisteredDevice] = useState<string | null>(null);
  useRegistered(() => {
    const added = cameras.find((camera) => camera.source.device_id === registeredDevice) ?? cameras.at(-1);
    if (added) navigate(`/cameras/${added.id}`, { replace: true });
  });
  if (cameraId && !adding && !chosen) return <Navigate to="/cameras" replace />;
  const own = cameras.filter((c) => !c.printer_id);
  const fromPrinters = cameras.filter((c) => c.printer_id);
  const shown = group === "cameras" ? own : fromPrinters;
  const selected = adding ? undefined : (chosen ?? own[0] ?? fromPrinters[0]);
  const hasPrinters = (engine?.printers ?? []).length > 0;
  const refreshing = isPending("printer.cameras.refresh");
  const registerDevice = (name: string, source: CameraSource) => {
    setRegisteredDevice(source.device_id ?? null);
    send({ cmd: "camera.add", name, source });
  };
  const list = (
    <>
      <Tabs
        prefix="cameras"
        label="Camera groups"
        cells
        tabs={[
          { id: "cameras", label: `Cameras · ${own.length}` },
          { id: "printers", label: `Printer cams · ${fromPrinters.length}` },
        ]}
        value={group}
        onChange={setGroup}
      />
      <TabPanel prefix="cameras" id={group}>
        {shown.map((camera) => (
          <CameraLink key={camera.id} camera={camera} selected={camera.id === selected?.id} />
        ))}
        {group === "cameras" && own.length === 0 && <p className="border-b border-line-0 px-4 py-3 text-sm text-text-2">No cameras registered yet.</p>}
        {group === "cameras" ? (
          <Link to="/cameras/new" aria-current={adding ? "page" : undefined} className="list-row font-mono text-xs font-semibold uppercase tracking-[0.06em]">
            + Register a camera
          </Link>
        ) : (
          <div className="space-y-3 px-4 py-3">
            <p className="text-sm text-text-1">Cameras connected to your registered printers. Refresh to register any added since.</p>
            {!hasPrinters && <p className="mono text-xs text-text-2">register a printer first</p>}
            {hasPrinters && !fromPrinters.length && <p className="mono text-xs text-text-2">no printer cameras found, refresh after connecting one</p>}
            <button className="btn" disabled={!hasPrinters || refreshing} onClick={() => send({ cmd: "printer.cameras.refresh" })}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        )}
      </TabPanel>
    </>
  );
  const detail = selected ? (
    <CameraEditor key={selected.id} camera={selected} />
  ) : (
    <>
      <DetailHead title="Register a camera" />
      <AddCamera onDeviceAdd={registerDevice} />
    </>
  );
  return (
    <Page title="Cameras" back={cameraId ? { to: "/cameras", label: "Back" } : undefined} backOnPhones subview={Boolean(cameraId)}>
      <Split list={list} detail={detail} detailShown={Boolean(cameraId)} />
    </Page>
  );
}
