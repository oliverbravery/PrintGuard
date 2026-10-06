import { printerAccepts } from "../prints";
import { useStore } from "../store";
import type { Printer } from "../types";

export function PrinterTags({ selected, ext, onToggle }: { selected: string[]; ext: string; onToggle: (id: string) => void }) {
  const engine = useStore((s) => s.engine);
  const printers = engine?.printers ?? [];
  if (!engine || !printers.length) return <p className="mono text-[0.68rem] text-text-2">register a printer to tag files for it</p>;
  const refusing = printers.filter((printer) => !printerAccepts(engine, printer, ext));
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {printers.map((printer: Printer) => {
          const accepts = !refusing.includes(printer);
          const on = selected.includes(printer.id);
          return (
            <button
              key={printer.id}
              type="button"
              className={`chip cursor-pointer hover:opacity-80 ${on ? "chip-accent" : ""} ${accepts ? "" : "opacity-40"}`}
              aria-pressed={on}
              disabled={!accepts}
              title={accepts ? `${on ? "Untag" : "Tag"} for ${printer.name}` : undefined}
              onClick={() => onToggle(printer.id)}
            >
              {on ? "✓ " : ""}
              {printer.name}
            </button>
          );
        })}
      </div>
      {refusing.length > 0 && (
        <p className="text-[0.66rem] text-text-2">
          {refusing.map((printer) => printer.name).join(", ")} can't print .{ext} files.
        </p>
      )}
    </div>
  );
}
