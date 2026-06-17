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
  const saving = isPending("monitor.add");
  const sent = useRef(false);
  const close = () => openDialog(null);

  useEffect(() => {
    if (sent.current && !saving) {
      close();
      openDetail(null);
    }
  }, [saving]);

  return (
    <Dialog title="Add monitor" onClose={close}>
      <div className="space-y-3">
        <input className="field" placeholder="Monitor name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <select className="field" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
          <option value="">Bind a camera…</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.max_fps.toFixed(0)} fps)
            </option>
          ))}
        </select>
        {!cameras.length && (
          <p className="text-xs text-text-1">No cameras registered yet — add one from the camera registry first.</p>
        )}
        <select className="field" value={printerId} onChange={(e) => setPrinterId(e.target.value)}>
          <option value="">No printer (alerts only)</option>
          {printers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          className="btn btn-primary w-full"
          disabled={!name.trim() || !cameraId || saving}
          onClick={() => {
            sent.current = true;
            send({ cmd: "monitor.add", monitor: { name: name.trim(), camera_id: cameraId, printer_id: printerId } });
          }}
        >
          {saving ? "Adding…" : "Add monitor"}
        </button>
      </div>
    </Dialog>
  );
}
