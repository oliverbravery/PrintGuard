import { useEffect, useState } from "react";
import { bedCamera, eligiblePrinters } from "../prints";
import { useStore } from "../store";
import type { PrintFile, Printer } from "../types";
import { Dialog } from "./Dialog";
import { Feed } from "./Feed";

function BedCheck({ print, printer, onStart, onClose }: { print: PrintFile; printer: Printer; onStart: () => void; onClose: () => void }) {
  const engine = useStore((s) => s.engine);
  const idle = printer.device_state?.status === "idle";
  return (
    <Dialog title={`Print ${print.name} on ${printer.name}`} onClose={onClose}>
      <div className="space-y-4">
        <div className="overflow-hidden rounded border border-line-0">
          <Feed camera={engine ? bedCamera(engine, printer.id) : undefined} />
        </div>
        <p className="text-sm text-text-0">Is the build plate on and the bed clear?</p>
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!idle} title={idle ? undefined : `${printer.name} has to be idle first`} onClick={onStart}>
            Start print
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function SendToPrinter({ print }: { print: PrintFile }) {
  const { engine, send, isPending } = useStore();
  const printers = engine ? eligiblePrinters(engine, print) : [];
  const [printerId, setPrinterId] = useState(printers[0]?.id ?? "");
  const [checkingBed, setCheckingBed] = useState(false);
  const chosen = printers.find((p) => p.id === printerId) ?? printers[0];
  const status = chosen?.device_state?.status;
  const busy = isPending("print.start", print.id);

  useEffect(() => {
    if (!printers.some((p) => p.id === printerId)) setPrinterId(printers[0]?.id ?? "");
  }, [printers.map((p) => p.id).join(",")]);

  if (!printers.length) {
    return (
      <p className="mono text-[0.68rem] text-text-2">
        {print.printer_ids.length ? "none of its printers is registered" : `no registered printer takes .${print.ext} files`}
      </p>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <select className="field" value={chosen?.id ?? ""} onChange={(e) => setPrinterId(e.target.value)} aria-label="Printer to send to">
        {printers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {p.device_state?.status ?? "no state yet"}
          </option>
        ))}
      </select>
      <button
        className="btn btn-primary shrink-0"
        disabled={!chosen || status !== "idle" || busy}
        title={status === "idle" ? `Send ${print.name} to ${chosen?.name}` : `${chosen?.name ?? "The printer"} has to be idle first`}
        onClick={() => setCheckingBed(true)}
      >
        {busy ? "Sending…" : "Print"}
      </button>
      {checkingBed && chosen && (
        <BedCheck
          print={print}
          printer={chosen}
          onClose={() => setCheckingBed(false)}
          onStart={() => {
            send({ cmd: "print.start", id: print.id, printer_id: chosen.id });
            setCheckingBed(false);
          }}
        />
      )}
    </div>
  );
}
