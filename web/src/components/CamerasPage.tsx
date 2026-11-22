import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { listVideoInputs } from "../media";
import { useStore } from "../store";
import type { Camera, CameraSource } from "../types";
import { publishStream, published } from "../stream";
import { cameraStatus, sourceLabel } from "../cameras";
import { ConfirmButton } from "./ConfirmButton";
import { CropEditor, frameAspect, turnedCrop, type FrameSize } from "./CropEditor";
import { useCovered } from "./Feed";
import { NameField } from "./NameField";
import { SaveStatus } from "./SaveStatus";
import { Slider } from "./Slider";
import { Dialog } from "./Dialog";
import { AddCell, DetailHead, Page, Split } from "./Page";
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
    ? "Added automatically by its printer integration. Remove the printer if you want to remove this camera."
    : camera.declared
      ? "Passed into the container at startup. Remove its devices entry from your Docker config to remove it."
      : null;
  const detectFpsCeiling = Math.min(UNCAPPED_DETECT_FPS, Math.ceil(camera.max_fps));
  const covered = useCovered();
  const [frame, setFrame] = useState<FrameSize | null>(null);
  const rotate = (rotation: number) => {
    const turned = (rotation - camera.rotation) % 180 !== 0;
    updateCamera(camera.id, turned && camera.crop ? { rotation, crop: turnedCrop(camera.crop, frameAspect(frame, camera.rotation)) } : { rotation });
  };
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
          <CropEditor camera={camera} active={!covered} frame={frame} onFrame={setFrame} onChange={(crop) => updateCamera(camera.id, { crop })} />
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
              hint="The preview sharpens at display size, so it looks a bit stronger here than what the model actually sees."
              onChange={(v) => updateCamera(camera.id, { sharpness: v })}
            />
            <Slider
              label="Detection rate"
              value={Math.min(camera.detect_fps, detectFpsCeiling)}
              min={0.5}
              max={detectFpsCeiling}
              step={0.5}
              format={(v) => `${v} fps`}
              hint="Lower this to cut CPU load on the hub. Defects will take a little longer to confirm at lower rates."
              onChange={(v) => updateCamera(camera.id, { detect_fps: v >= detectFpsCeiling ? UNCAPPED_DETECT_FPS : v })}
            />
          </div>
          <Segmented
            label="Rotation"
            options={[0, 90, 180, 270].map((deg) => ({ value: String(deg), label: `${deg}°` }))}
            value={String(camera.rotation ?? 0)}
            onChange={(deg) => rotate(Number(deg))}
          />
        </div>
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
    const device = devices.find((d) => d.device_id === deviceId);
    if (!device || busy) return;
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
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (tab === "browser" && !desktopApp) {
      listVideoInputs()
        .then((inputs) => mounted.current && setDevices(inputs))
        .catch((err) => toast("error", `camera access: ${err instanceof Error ? err.message : err}`));
    }
  }, [tab]);

  const publish = async () => {
    if (!deviceId || busy || isPending("camera.add")) return;
    setBusy(true);
    try {
      const path = `dev-${slug(name || "camera")}-${Date.now().toString(36)}`;
      const { stop, hlsPlayable } = await publishStream(path, deviceId, (reason) =>
        toast("error", `publishing stopped: ${reason}`),
      );
      if (!mounted.current) {
        stop();
        return;
      }
      if (!hlsPlayable) {
        toast("alert", "This browser records VP8, which the dashboard can't play, so this camera is monitored but has no live view. Chrome, Edge and Safari record H.264.");
      }
      await new Promise((r) => setTimeout(r, 800));
      if (!mounted.current) {
        stop();
        return;
      }
      addPublishedCamera(name || "Published camera", path);
    } catch (err) {
      toast("error", `publish failed: ${err}`);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const tabs: Array<[AddTab, string]> = [
    ["url", "Stream URL"],
    ["machine", "This machine"],
    ...(desktopApp ? [] : ([["browser", "This browser"]] as Array<[AddTab, string]>)),
  ];
  return (
    <div className="space-y-4">
      <Segmented label="Source" options={tabs.map(([value, label]) => ({ value, label }))} value={tab} onChange={setTab} />
      {tab === "url" && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!url.trim() || isPending("camera.add")) return;
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
            USB webcams plugged straight into the machine running PrintGuard. They live on the hub itself, so they keep
            watching even when every browser tab is closed.
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
            Streams this phone or laptop's camera straight to the hub. It reconnects automatically if the hub restarts
            and resumes whenever you reopen this page here.
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

export function CameraDialog() {
  const { engine, send, openDialog } = useStore();
  const navigate = useNavigate();
  const cameras = engine?.cameras ?? [];
  const [registeredDevice, setRegisteredDevice] = useState<string | null>(null);
  const close = () => openDialog(null);
  useRegistered(() => {
    const added = (registeredDevice ? cameras.find((camera) => camera.source.device_id === registeredDevice) : undefined) ?? cameras.at(-1);
    close();
    if (added) navigate(`/cameras/${added.id}`);
  });
  return (
    <Dialog title="Register a camera" onClose={close}>
      <AddCamera
        onDeviceAdd={(name, source) => {
          setRegisteredDevice(source.device_id ?? null);
          send({ cmd: "camera.add", name, source });
        }}
      />
    </Dialog>
  );
}

type Group = "cameras" | "printers";

export function CamerasPage() {
  const { cameraId } = useParams();
  const { engine, send, isPending, openDialog } = useStore();
  const cameras = engine?.cameras ?? [];
  const chosen = cameras.find((camera) => camera.id === cameraId);
  const [group, setGroup] = useState<Group>(chosen?.printer_id ? "printers" : "cameras");
  useEffect(() => {
    if (chosen) setGroup(chosen.printer_id ? "printers" : "cameras");
  }, [chosen?.id, chosen?.printer_id]);
  if (cameraId && !chosen) return <Navigate to="/cameras" replace />;
  const own = cameras.filter((c) => !c.printer_id);
  const fromPrinters = cameras.filter((c) => c.printer_id);
  const shown = group === "cameras" ? own : fromPrinters;
  const selected = chosen ?? own[0] ?? fromPrinters[0];
  const hasPrinters = (engine?.printers ?? []).length > 0;
  const refreshing = isPending("printer.cameras.refresh");
  const list = (
    <>
      <div className="flex *:first:min-w-0 *:first:flex-1">
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
        <span className="flex border-b border-rule">
          <AddCell label="Add camera" onClick={() => openDialog("camera")} />
        </span>
      </div>
      <TabPanel prefix="cameras" id={group}>
        {shown.map((camera) => (
          <CameraLink key={camera.id} camera={camera} selected={camera.id === selected?.id} />
        ))}
        {group === "cameras" && own.length === 0 && <p className="border-b border-line-0 px-4 py-3 text-sm text-text-2">No cameras registered yet.</p>}
        {group === "printers" && (
          <div className="space-y-3 px-4 py-3">
            <p className="text-sm text-text-1">Webcams exposed by your registered printers. Hit Refresh if you've added a camera since connecting a printer.</p>
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
      <DetailHead title="No cameras" />
      <p className="px-4 py-4 text-sm text-text-2">Press + Add to register one.</p>
    </>
  );
  return (
    <Page title="Cameras" phoneBack={cameraId ? { to: "/cameras", label: "Back" } : undefined} subview={Boolean(cameraId)}>
      <Split list={list} detail={detail} detailShown={Boolean(cameraId)} />
    </Page>
  );
}
