import { printerAccepts } from "../prints";
import { useStore } from "../store";
import type { Printer } from "../types";

export function PrinterTags({ selected, ext, onToggle }: { selected: string[]; ext: string; onToggle: (id: string) => void }) {
  const engine = useStore((s) => s.engine);
  const printers = engine?.printers ?? [];
  if (!engine || !printers.length) return <p className="mono text-[0.68rem] text-text-2">register a printer to tag files for it</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {printers.map((printer: Printer) => {
        const accepts = printerAccepts(engine, printer, ext);
        const on = selected.includes(printer.id);
        return (
          <button
            key={printer.id}
            type="button"
            className={`chip cursor-pointer hover:opacity-80 ${on ? "chip-accent" : ""} ${accepts ? "" : "opacity-40"}`}
            aria-pressed={on}
            disabled={!accepts}
            title={accepts ? `${on ? "Untag" : "Tag"} for ${printer.name}` : `${printer.name} cannot print .${ext} files`}
            onClick={() => onToggle(printer.id)}
          >
            {on ? "✓ " : ""}
            {printer.name}
          </button>
        );
      })}
    </div>
  );
}
