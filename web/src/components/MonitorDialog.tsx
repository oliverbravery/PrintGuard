import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

export function MonitorDialog() {
  const { engine, send, openDialog, openDetail, isPending } = useStore();
  const [name, setName] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [printerId, setPrinterId] = useState("");
  const cameras = engine?.cameras ?? [];
  const printers = engine?.printers ?? [];
  const monitors = engine?.monitors.length ?? 0;
  const monitorsWhenSent = useRef<number | null>(null);
  const boundCameraId = cameras.some((c) => c.id === cameraId) ? cameraId : "";
  const boundPrinterId = printers.some((p) => p.id === printerId) ? printerId : "";
  const saving = isPending("monitor.add");
  const close = () => openDialog(null);

  useEffect(() => {
    if (saving || monitorsWhenSent.current === null) return;
    if (monitors > monitorsWhenSent.current) {
      close();
      openDetail(null);
    }
    monitorsWhenSent.current = null;
  }, [saving]);

  return (
    <Dialog title="Add monitor" onClose={close}>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          monitorsWhenSent.current = monitors;
          send({ cmd: "monitor.add", monitor: { name: name.trim(), camera_id: boundCameraId, printer_id: boundPrinterId } });
        }}
      >
        <input className="field" aria-label="Monitor name" placeholder="Monitor name" value={name} onChange={(e) => setName(e.target.value)} />
        <select className="field" aria-label="Camera" value={boundCameraId} onChange={(e) => setCameraId(e.target.value)}>
          <option value="">Bind a camera…</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.max_fps.toFixed(0)} fps)
            </option>
          ))}
        </select>
        {!cameras.length && (
          <p className="text-xs text-text-1">No cameras registered yet, add one from the camera registry first.</p>
        )}
        <select className="field" aria-label="Printer" value={boundPrinterId} onChange={(e) => setPrinterId(e.target.value)}>
          <option value="">No printer (alerts only)</option>
          {printers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn-primary w-full" disabled={!name.trim() || !boundCameraId || saving}>
          {saving ? "Adding…" : "Add monitor"}
        </button>
      </form>
    </Dialog>
  );
}
