import { formatBytes } from "../prints";
import { useStore } from "../store";
import type { PrintFile } from "../types";
import { Sheet } from "./Dialog";
import { PrintStats } from "./PrintStats";
import { SendToPrinter } from "./SendToPrinter";
import { Toolpath } from "./Toolpath";

async function storedGcode(print: PrintFile): Promise<string | null> {
  const response = await fetch(`api/prints/${print.id}/gcode`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

export function PrintViewer({ print }: { print: PrintFile }) {
  const openPrint = useStore((s) => s.openPrint);
  const close = () => openPrint(null);
  return (
    <Sheet
      title={print.name}
      onClose={close}
      closeLabel="Close print viewer"
      width="sm:w-[680px]"
      meta={
        <>
          <span className="chip">.{print.ext}</span>
          <span className="chip">{formatBytes(print.size)}</span>
        </>
      }
    >
      <Toolpath key={print.id} label={print.name} load={() => storedGcode(print)} />

      <div className="border-b border-line-0 px-5 py-4">
        <PrintStats meta={print.meta} temperatures />
      </div>

      <section className="px-5 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        <h3 className="display mb-3 text-[0.68rem] font-semibold tracking-[0.24em] text-text-2">Send to a printer</h3>
        <SendToPrinter print={print} />
      </section>
    </Sheet>
  );
}
