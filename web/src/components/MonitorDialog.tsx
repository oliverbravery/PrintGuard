import { useState } from "react";
import { useNavigate } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { useCreated } from "../submit";
import { Dialog } from "./Dialog";

export function MonitorDialog() {
  const { engine, send, openDialog, saving } = useStore(
    useShallow((s) => ({
      engine: s.engine,
      send: s.send,
      openDialog: s.openDialog,
      saving: s.isPending("monitor.add"),
    })),
  );
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [printerId, setPrinterId] = useState("");
  const cameras = engine?.cameras ?? [];
  const printers = engine?.printers ?? [];
  const monitors = engine?.monitors ?? [];
  const boundCameraId = cameras.some((c) => c.id === cameraId) ? cameraId : "";
  const boundPrinterId = printers.some((p) => p.id === printerId) ? printerId : "";
  const close = () => openDialog(null);

  useCreated("monitor.add", monitors, (added) => {
    close();
    navigate(`/monitors/${added.id}`);
  });

  return (
    <Dialog title="Add monitor" onClose={close}>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim() || !boundCameraId || saving) return;
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
          <p className="text-sm text-text-1">No cameras registered yet. Add one on the Cameras page first.</p>
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
