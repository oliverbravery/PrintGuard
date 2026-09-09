import { useEffect, useState } from "react";
import { eligiblePrinters } from "../prints";
import { useStore } from "../store";
import type { PrintFile } from "../types";

export function SendToPrinter({ print }: { print: PrintFile }) {
  const { engine, send, isPending } = useStore();
  const printers = engine ? eligiblePrinters(engine, print) : [];
  const [printerId, setPrinterId] = useState(printers[0]?.id ?? "");
  const chosen = printers.find((p) => p.id === printerId) ?? printers[0];
  const status = chosen?.device_state?.status;
  const busy = isPending("print.start");

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
        onClick={() => chosen && send({ cmd: "print.start", id: print.id, printer_id: chosen.id })}
      >
        {busy ? "Sending…" : "Print"}
      </button>
    </div>
  );
}
