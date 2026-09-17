import { useEffect, useState } from "react";
import { acceptedTags, extOf, formatBytes, inspectPrint, isText, toolpathOf, type Inspection, type Temperatures } from "../prints";
import { useStore, type StagedPrint } from "../store";
import { Sheet } from "./Dialog";
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
  tags,
  onToggleTag,
  onDone,
}: {
  staged: StagedPrint;
  tags: string[];
  onToggleTag: (id: string) => void;
  onDone: () => void;
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
  const [tags, setTags] = useState<string[]>([]);
  const [current] = staged;
  const close = () => staged.forEach((p) => unstage(p.id));
  return (
    <Sheet
      title={`Upload ${current.file.name}`}
      onClose={close}
      closeLabel="Cancel uploads"
      width="sm:w-[680px]"
      meta={
        <>
          {staged.length > 1 && <span className="chip">{staged.length - 1} more</span>}
          <span className="chip">{formatBytes(current.file.size)}</span>
        </>
      }
    >
      <StagedPrintForm
        key={current.id}
        staged={current}
        tags={tags}
        onToggleTag={(id) => setTags((t) => (t.includes(id) ? t.filter((p) => p !== id) : [...t, id]))}
        onDone={() => unstage(current.id)}
      />
    </Sheet>
  );
}
