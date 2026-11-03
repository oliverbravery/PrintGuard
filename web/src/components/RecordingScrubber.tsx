import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { elapsed, recordedFrameKey } from "../review";
import { useStore } from "../store";
import type { Review, ReviewFrame } from "../types";
import { Slider } from "./Slider";

const SETTLE_MS = 80;

function markColour(frame: ReviewFrame): string {
  if (frame.kind === "alert") return "bg-bad";
  return frame.kind === "added" ? "bg-text-0" : "bg-accent";
}

export function RecordingScrubber({ review, full, onAdd }: { review: Review; full: boolean; onAdd: (index: number, label: "good" | "failure") => void }) {
  const { snapshotCache, fetchRecordedFrame, reconnecting, isPending } = useStore();
  const timeline = review.timeline;
  const last = timeline.length - 1;
  const [index, setIndex] = useState(last);
  const [shown, setShown] = useState<string>();
  const start = timeline[0][0];
  const span = Math.max(1, timeline[last][0] - start);
  const [ts, score] = timeline[index];
  const url = snapshotCache[recordedFrameKey(review.id, index)];
  const added = review.frames.some((frame) => frame.kind === "added" && frame.ts === ts);
  const adding = isPending("review.add", review.id);
  const describe = (at: number) => `${elapsed(timeline[at][0] - start)} in · ${(timeline[at][1] * 100).toFixed(0)}%`;

  useEffect(() => {
    if (reconnecting) return;
    const timer = setTimeout(() => fetchRecordedFrame(review.id, index), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [review.id, index, reconnecting]);

  useEffect(() => {
    if (url) setShown(url);
  }, [url]);

  const step = (by: number) => setIndex((at) => Math.min(last, Math.max(0, at + by)));

  return (
    <section className="space-y-2" aria-label="Whole print">
      <div className="panel relative aspect-video overflow-hidden bg-ink-0">
        {shown && <img src={shown} alt={`The print ${elapsed(ts - start)} in, scored ${(score * 100).toFixed(0)}%`} className="h-full w-full object-contain" />}
        {!url && (
          <span role="status" className="label absolute right-2 bottom-2">
            loading
          </span>
        )}
      </div>
      <Slider
        label="Whole print"
        value={index}
        min={0}
        max={last}
        step={1}
        format={describe}
        onChange={setIndex}
        marks={review.frames.map((frame) => (
          <span
            key={frame.id}
            className={`absolute top-0 h-2 w-[3px] -translate-x-1/2 rounded-sm ${markColour(frame)}`}
            style={{ left: `${((frame.ts - start) / span) * 100}%` }}
          />
        ))}
      />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn tap-target" aria-label="Previous frame" disabled={index === 0} onClick={() => step(-1)}>
          <ChevronLeft size={14} aria-hidden />
        </button>
        <button type="button" className="btn tap-target" aria-label="Next frame" disabled={index === last} onClick={() => step(1)}>
          <ChevronRight size={14} aria-hidden />
        </button>
        <span className="flex-1" />
        <button type="button" className="btn" disabled={full || added || adding} onClick={() => onAdd(index, "good")}>
          Add as good
        </button>
        <button type="button" className="btn" disabled={full || added || adding} onClick={() => onAdd(index, "failure")}>
          Add as failure
        </button>
      </div>
    </section>
  );
}
