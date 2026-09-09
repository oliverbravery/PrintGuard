import { useRef, useState, type DragEvent } from "react";
import { ACCEPT, ago, formatBytes, printerAccepts, summary } from "../prints";
import { useStore } from "../store";
import type { PrintFile, Printer } from "../types";
import { Dialog } from "./Dialog";
import { NameField } from "./NameField";
import { SendToPrinter } from "./SendToPrinter";

function PrinterTags({ selected, ext, onToggle }: { selected: string[]; ext?: string; onToggle: (id: string) => void }) {
  const engine = useStore((s) => s.engine);
  const printers = engine?.printers ?? [];
  if (!engine || !printers.length) return <p className="mono text-[0.68rem] text-text-2">register a printer to tag files for it</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {printers.map((printer: Printer) => {
        const accepts = ext === undefined || printerAccepts(engine, printer, ext);
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

function Thumbnail({ print }: { print: PrintFile }) {
  return (
    <div className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded border border-line-0 bg-ink-0">
      {print.thumbnail ? (
        <img src={`api/prints/${print.id}/thumbnail`} alt="" className="h-full w-full object-contain" />
      ) : (
        <span className="mono text-[0.6rem] uppercase text-text-2">.{print.ext}</span>
      )}
    </div>
  );
}

function PrintRow({ print }: { print: PrintFile }) {
  const { send, isPending, openPrint } = useStore();
  const [editing, setEditing] = useState(false);
  const removing = isPending("print.remove");
  const toggleTag = (id: string) => {
    const printer_ids = print.printer_ids.includes(id) ? print.printer_ids.filter((p) => p !== id) : [...print.printer_ids, id];
    send({ cmd: "print.update", id: print.id, patch: { printer_ids } });
  };
  return (
    <div className="panel space-y-2.5 px-3 py-2.5">
      <div className="flex items-start gap-3">
        <button type="button" className="cursor-pointer" aria-label={`View ${print.name}`} onClick={() => openPrint(print.id)}>
          <Thumbnail print={print} />
        </button>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-sm font-medium">{print.name}</div>
          <div className="mono mt-0.5 text-[0.62rem] text-text-2">{[...summary(print), formatBytes(print.size), ago(print.uploaded)].join(" · ")}</div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => openPrint(print.id)}>
            View
          </button>
          <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setEditing((v) => !v)}>
            {editing ? "Hide" : "Edit"}
          </button>
          <button
            className="btn btn-danger !py-1 !px-2.5 !text-[0.62rem]"
            disabled={removing}
            onClick={() => send({ cmd: "print.remove", id: print.id })}
          >
            {removing ? "Removing…" : "Remove"}
          </button>
        </div>
      </div>
      {editing && <NameField name={print.name} onRename={(name) => send({ cmd: "print.update", id: print.id, patch: { name } })} />}
      <PrinterTags selected={print.printer_ids} ext={print.ext} onToggle={toggleTag} />
      <SendToPrinter print={print} />
    </div>
  );
}

function DropZone({ tags }: { tags: string[] }) {
  const uploadPrints = useStore((s) => s.uploadPrints);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const take = (files: FileList | null) => files && uploadPrints(Array.from(files), tags);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    take(event.dataTransfer.files);
  };
  return (
    <div
      className={`rounded border border-dashed px-4 py-5 text-center transition-colors ${over ? "border-accent bg-accent/5" : "border-line-1 bg-ink-0/40"}`}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <input ref={input} type="file" accept={ACCEPT} multiple className="sr-only" onChange={(e) => take(e.target.files)} />
      <p className="text-sm text-text-0">
        Drop sliced files here, or{" "}
        <button type="button" className="text-accent underline hover:opacity-80" onClick={() => input.current?.click()}>
          browse
        </button>
      </p>
      <p className="mono mt-1 text-[0.66rem] text-text-2">gcode, bgcode or a sliced 3mf</p>
    </div>
  );
}

export function PrintsDialog() {
  const { engine, openDialog, uploads } = useStore();
  const [filter, setFilter] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const close = () => openDialog(null);
  const printers = engine?.printers ?? [];
  const prints = (engine?.prints ?? [])
    .filter((p) => !filter || p.printer_ids.includes(filter))
    .sort((a, b) => b.uploaded - a.uploaded);
  return (
    <Dialog title="Print library" size="wide" fixed onClose={close}>
      <div className="flex h-full min-h-0 flex-col gap-4">
        <div className="space-y-2.5">
          <DropZone tags={tags} />
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Tag uploads for</span>
            <PrinterTags selected={tags} onToggle={(id) => setTags((t) => (t.includes(id) ? t.filter((p) => p !== id) : [...t, id]))} />
          </div>
          {uploads.map((upload) => (
            <div
              key={upload.id}
              className="flex items-center gap-3"
              role="progressbar"
              aria-label={`Uploading ${upload.name}`}
              aria-valuenow={Math.round(upload.progress * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span className="mono min-w-0 flex-1 truncate text-[0.68rem] text-text-1">{upload.name}</span>
              <div aria-hidden className="h-1.5 w-40 overflow-hidden rounded-full bg-accent/25">
                <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${upload.progress * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="label">
            {prints.length} {prints.length === 1 ? "file" : "files"}
          </span>
          <div className="hairline flex-1" />
          {printers.length > 0 && (
            <select className="field !w-auto" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by printer">
              <option value="">All printers</option>
              {printers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {prints.map((print) => (
            <PrintRow key={print.id} print={print} />
          ))}
          {!prints.length && (
            <p className="mono text-[0.7rem] text-text-2">
              {filter ? "nothing is tagged for this printer" : "nothing uploaded yet, sliced files you drop here stay on the hub"}
            </p>
          )}
        </div>
      </div>
    </Dialog>
  );
}
