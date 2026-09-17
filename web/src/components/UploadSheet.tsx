import { useEffect, useId, useState } from "react";
import { acceptedTags, extOf, formatBytes, inspectPrint, isText, toolpathOf, type Inspection, type Temperatures } from "../prints";
import { useStore, type StagedPrint } from "../store";
import { Modal } from "./Dialog";
import { HEATER_MAX, HEATERS, type HeaterName } from "./PrinterControls";
import { PrinterTags } from "./PrinterTags";
import { PrintStats } from "./PrintStats";
import { Toolpath } from "./Toolpath";

function stem(filename: string): string {
  return filename.includes(".") ? filename.slice(0, filename.lastIndexOf(".")) : filename;
}

function TemperatureField({ heater, value, heats, onChange }: { heater: HeaterName; value: string; heats: boolean; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center gap-2">
      <span className="label w-12">{heater}</span>
      <input
        className="field !w-20 text-right"
        type="number"
        inputMode="numeric"
        min={1}
        max={HEATER_MAX[heater]}
        placeholder="—"
        disabled={!heats}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="mono text-[0.7rem] text-text-2">°C</span>
    </label>
  );
}

function StagedPrintForm({
  staged,
  queued,
  titleId,
  tags,
  onToggleTag,
  onDone,
  onClose,
}: {
  staged: StagedPrint;
  queued: number;
  titleId: string;
  tags: string[];
  onToggleTag: (id: string) => void;
  onDone: () => void;
  onClose: () => void;
}) {
  const { engine, uploadPrint } = useStore();
  const { file } = staged;
  const ext = extOf(file.name);
  const [toolpath] = useState(() => toolpathOf(file));
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState(stem(file.name));
  const [drafts, setDrafts] = useState<Record<HeaterName, string>>({ nozzle: "", bed: "" });
  const printerIds = engine ? acceptedTags(engine, tags, ext) : [];

  useEffect(() => {
    let current = true;
    toolpath
      .then((path) => inspectPrint(file, path))
      .then((result) => {
        if (!current) return;
        setInspection(result);
        setDrafts({ nozzle: String(result.meta.nozzle ?? ""), bed: String(result.meta.bed ?? "") });
      })
      .catch((err: Error) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, []);

  const temperatures: Temperatures = {};
  let valid = inspection !== null;
  for (const heater of HEATERS) {
    const sliced = inspection?.meta[heater];
    const target = Number(drafts[heater]);
    if (!sliced) continue;
    if (!drafts[heater].trim() || !(target > 0 && target <= HEATER_MAX[heater])) valid = false;
    else if (target !== sliced) temperatures[heater] = target;
  }

  const upload = () => {
    uploadPrint({
      file,
      name: name.trim(),
      printerIds,
      temperatures,
      drawPreview: isText(file.name) && !inspection!.thumbnail,
    });
    onDone();
  };

  return (
    <>
      <div className="sticky top-0 z-10 flex items-center gap-2.5 border-b border-line-0 bg-ink-1/95 px-5 py-3.5 backdrop-blur-sm">
        <h2 id={titleId} className="display flex-1 truncate text-lg font-semibold">
          Upload {file.name}
        </h2>
        {queued > 0 && <span className="chip">{queued} more</span>}
        <span className="chip">{formatBytes(file.size)}</span>
        <button type="button" className="cursor-pointer text-2xl leading-none text-text-2 hover:text-accent" onClick={onClose} aria-label="Cancel uploads">
          ×
        </button>
      </div>

      <Toolpath label={file.name} load={() => toolpath.then((path) => path && path.text())} />

      <div className="flex-1 space-y-4 px-5 py-4">
        <PrintStats meta={inspection?.meta ?? null} />
        <label className="block">
          <span className="label mb-1 block">Name</span>
          <input className="field" value={name} maxLength={80} placeholder={stem(file.name)} onChange={(e) => setName(e.target.value)} />
        </label>
        <div>
          <span className="label mb-1 block">First layer temperatures</span>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {HEATERS.map((heater) => (
              <TemperatureField
                key={heater}
                heater={heater}
                value={drafts[heater]}
                heats={Boolean(inspection?.meta[heater])}
                onChange={(value) => setDrafts((d) => ({ ...d, [heater]: value }))}
              />
            ))}
          </div>
          {ext === "bgcode" && <p className="mono mt-1.5 text-[0.66rem] text-text-2">binary gcode prints at the temperatures it was sliced with</p>}
        </div>
        <div>
          <span className="label mb-1 block">Tag for</span>
          <PrinterTags selected={printerIds} ext={ext} onToggle={onToggleTag} />
        </div>
        {error && (
          <p role="alert" className="mono text-[0.7rem] text-bad">
            {error}
          </p>
        )}
      </div>

      <div className="sticky bottom-0 flex justify-end gap-2 border-t border-line-0 bg-ink-1/95 px-5 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur-sm">
        <button className="btn" onClick={onDone}>
          Discard
        </button>
        <button className="btn btn-primary" disabled={!valid} onClick={upload}>
          {inspection || error ? "Upload" : "Reading…"}
        </button>
      </div>
    </>
  );
}

export function UploadSheet() {
  const { staged, unstage } = useStore();
  const titleId = useId();
  const [tags, setTags] = useState<string[]>([]);
  const [current] = staged;
  const close = () => staged.forEach((p) => unstage(p.id));
  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in flex h-full w-full flex-col overflow-y-auto border-l border-line-0 bg-ink-1 sm:w-[680px]">
        <StagedPrintForm
          key={current.id}
          staged={current}
          queued={staged.length - 1}
          titleId={titleId}
          tags={tags}
          onToggleTag={(id) => setTags((t) => (t.includes(id) ? t.filter((p) => p !== id) : [...t, id]))}
          onDone={() => unstage(current.id)}
          onClose={close}
        />
      </aside>
    </Modal>
  );
}
