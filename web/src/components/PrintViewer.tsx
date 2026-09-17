import { useId } from "react";
import { formatBytes } from "../prints";
import { useStore } from "../store";
import type { PrintFile } from "../types";
import { Modal } from "./Dialog";
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
  const titleId = useId();
  const close = () => openPrint(null);
  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in h-full w-full overflow-y-auto border-l border-line-0 bg-ink-1 sm:w-[680px]">
        <div className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-line-0 bg-ink-1/95 px-5 py-3.5 backdrop-blur-sm">
          <h2 id={titleId} className="display flex-1 truncate text-lg font-semibold">
            {print.name}
          </h2>
          <span className="chip">.{print.ext}</span>
          <span className="chip">{formatBytes(print.size)}</span>
          <button type="button" className="cursor-pointer text-2xl leading-none text-text-2 hover:text-accent" onClick={close} aria-label="Close print viewer">
            ×
          </button>
        </div>

        <Toolpath key={print.id} label={print.name} load={() => storedGcode(print)} />

        <div className="border-b border-line-0 px-5 py-4">
          <PrintStats meta={print.meta} temperatures />
        </div>

        <section className="px-5 py-4">
          <h3 className="display mb-3 text-[0.68rem] font-semibold tracking-[0.24em] text-text-2">Send to a printer</h3>
          <SendToPrinter print={print} />
        </section>
      </aside>
    </Modal>
  );
}
