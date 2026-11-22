import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { ACCEPT, acceptedTags, ago, formatBytes, summary } from "../prints";
import { useStore } from "../store";
import { tooLargeToDraw, type ToolpathSource } from "../toolpath";
import type { PrintFile } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { NameField } from "./NameField";
import { DetailHead, ListHead, Page, Split } from "./Page";
import { PrinterTags } from "./PrinterTags";
import { PrintStats } from "./PrintStats";
import { SendToPrinter } from "./SendToPrinter";
import { Toolpath } from "./Toolpath";

function Thumbnail({ print }: { print: PrintFile }) {
  return (
    <span aria-hidden className="grid size-12 shrink-0 place-items-center overflow-hidden border border-line-0 bg-ink-1">
      {print.thumbnail ? (
        <img src={`api/prints/${print.id}/thumbnail`} alt="" className="h-full w-full object-contain" />
      ) : (
        <span className="mono text-xs uppercase text-text-2">.{print.ext}</span>
      )}
    </span>
  );
}

async function storedGcode(print: PrintFile): Promise<ToolpathSource | null> {
  const response = await fetch(`api/prints/${print.id}/gcode`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const reader = response.body!.getReader();
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return new Blob(chunks);
    size += value.length;
    if (tooLargeToDraw({ size })) {
      void reader.cancel();
      return { size, text: async () => "" };
    }
    chunks.push(value);
  }
}

function PrintDetail({ print }: { print: PrintFile }) {
  const { send, isPending, updatePrint } = useStore();
  const removing = isPending("print.remove", print.id);
  const toggleTag = (id: string) => {
    const engine = useStore.getState().engine!;
    const tags = acceptedTags(engine, engine.prints.find((p) => p.id === print.id)!.printer_ids, print.ext);
    updatePrint(print.id, { printer_ids: tags.includes(id) ? tags.filter((p) => p !== id) : [...tags, id] });
  };
  return (
    <>
      <DetailHead title={print.name}>
        <span className="chip">.{print.ext}</span>
        <span className="chip">{formatBytes(print.size)}</span>
        <ConfirmButton
          disabled={removing}
          onConfirm={() => send({ cmd: "print.remove", id: print.id })}
        >
          {removing ? "Removing…" : "Remove"}
        </ConfirmButton>
      </DetailHead>
      <div className="grid xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="min-w-0 border-b border-line-0 xl:border-r">
          <Toolpath key={print.id} label={print.name} load={() => storedGcode(print)} />
        </div>
        <div className="min-w-0 border-b border-line-0">
          <div className="border-b border-line-0 px-4 py-4">
            <PrintStats meta={print.meta} temperatures />
          </div>
          <div className="space-y-4 px-4 py-4">
            <NameField name={print.name} onRename={(name) => updatePrint(print.id, { name })} />
            <PrinterTags selected={print.printer_ids} ext={print.ext} onToggle={toggleTag} />
          </div>
        </div>
      </div>
      <section className="px-4 py-4">
        <h3 className="label mb-3">Send to a printer</h3>
        <SendToPrinter print={print} />
      </section>
    </>
  );
}

function DropZone() {
  const stagePrints = useStore((s) => s.stagePrints);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const take = (files: FileList | null) => files && stagePrints(Array.from(files));

  useEffect(() => {
    const carriesFiles = (event: DragEvent) => event.dataTransfer?.types.includes("Files") ?? false;
    const allowDrop = (event: DragEvent) => carriesFiles(event) && event.preventDefault();
    const takeDrop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      setOver(false);
      take(event.dataTransfer!.files);
    };
    window.addEventListener("dragover", allowDrop);
    window.addEventListener("drop", takeDrop);
    return () => {
      window.removeEventListener("dragover", allowDrop);
      window.removeEventListener("drop", takeDrop);
    };
  }, []);

  return (
    <div
      className={`border border-dashed px-4 py-4 text-center transition-colors ${over ? "border-accent bg-ink-1" : "border-line-1"}`}
      onDragOver={() => setOver(true)}
      onDragLeave={() => setOver(false)}
    >
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
      <p className="text-sm text-text-0">
        Drop sliced files here, or{" "}
        <button type="button" className="tap-target text-accent underline hover:opacity-80" onClick={() => input.current?.click()}>
          browse
        </button>
      </p>
      <p className="mono mt-1 text-xs text-text-2">gcode, bgcode or a sliced 3mf</p>
    </div>
  );
}

export function PrintsPage() {
  const { printId } = useParams();
  const { engine, uploads } = useStore();
  const [chosenPrinter, setFilter] = useState("");
  const printers = engine?.printers ?? [];
  const filter = printers.some((p) => p.id === chosenPrinter) ? chosenPrinter : "";
  const library = engine?.prints ?? [];
  const prints = library.filter((p) => !filter || p.printer_ids.includes(filter)).sort((a, b) => b.uploaded - a.uploaded);
  const chosen = library.find((print) => print.id === printId);
  if (printId && !chosen) return <Navigate to="/prints" replace />;
  const selected = chosen ?? prints[0];
  const list = (
    <>
      <div className="space-y-2 border-b border-line-0 px-4 py-4">
        <DropZone />
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
            <span className="mono min-w-0 flex-1 truncate text-xs text-text-1">{upload.name}</span>
            <div aria-hidden className="h-1 w-32 overflow-hidden bg-line-0">
              <div className="h-full bg-accent transition-[width] duration-300" style={{ width: `${upload.progress * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <ListHead title={`${prints.length} ${prints.length === 1 ? "file" : "files"}`}>
        {printers.length > 0 && (
          <select className="field w-auto" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by printer">
            <option value="">All printers</option>
            {printers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
      </ListHead>
      {prints.map((print) => (
        <Link key={print.id} to={`/prints/${print.id}`} aria-current={print.id === selected?.id ? "page" : undefined} className="list-row">
          <Thumbnail print={print} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{print.name}</span>
            <span className="mono block text-xs text-text-2">{[...summary(print), formatBytes(print.size), ago(print.uploaded)].join(" · ")}</span>
          </span>
        </Link>
      ))}
      {!prints.length && (
        <p className="px-4 py-4 text-sm text-text-2">
          {filter ? "Nothing is tagged for this printer." : "Nothing uploaded yet. Sliced files you drop here stay on the hub."}
        </p>
      )}
    </>
  );
  return (
    <Page title="Prints" phoneBack={printId ? { to: "/prints", label: "Back" } : undefined} subview={Boolean(printId)}>
      <Split
        list={list}
        detail={
          selected ? (
            <PrintDetail key={selected.id} print={selected} />
          ) : (
            <>
              <DetailHead title="No file open" />
              <p className="px-4 py-4 text-sm text-text-2">Open a sliced file from the library to see its toolpath.</p>
            </>
          )
        }
        detailShown={Boolean(printId)}
      />
    </Page>
  );
}
