import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { elapsed, recordedFrameKey } from "../review";
import { useStore } from "../store";
import type { Review, ReviewFrame } from "../types";
import { Slider } from "./Slider";

const SETTLE_MS = 80;

function markStyle(frame: ReviewFrame): string {
  if (frame.kind === "alert") return "h-2 w-1.5 bg-bad";
  if (frame.kind === "spike") return "h-2 w-px bg-warn";
  return frame.kind === "added" ? "top-0.5 size-1.5 bg-accent" : "h-2 w-px bg-text-2";
}

export function RecordingScrubber({ review, full, onAdd }: { review: Review; full: boolean; onAdd: (index: number, label: "good" | "failure") => void }) {
  const timeline = review.timeline;
  const last = timeline.length - 1;
  const [index, setIndex] = useState(last);
  const [shown, setShown] = useState<string>();
  const { url, fetchRecordedFrame, reconnecting, adding } = useStore(
    useShallow((s) => ({
      url: s.snapshotCache[recordedFrameKey(review.id, index)],
      fetchRecordedFrame: s.fetchRecordedFrame,
      reconnecting: s.reconnecting,
      adding: s.isPending("review.add", review.id),
    })),
  );
  const start = timeline[0][0];
  const span = Math.max(1, timeline[last][0] - start);
  const [ts, score] = timeline[index];
  const added = review.frames.some((frame) => frame.kind === "added" && frame.ts === ts);
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
    <div className="space-y-3 px-4 py-4">
      <div className="relative aspect-video overflow-hidden border border-line-0 bg-ink-1">
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
            className={`absolute top-0 -translate-x-1/2 ${markStyle(frame)}`}
            style={{ left: `${Math.min(100, Math.max(0, ((frame.ts - start) / span) * 100))}%` }}
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
        <div className="flex basis-full gap-2 sm:ml-auto sm:basis-auto">
          <button type="button" className="btn flex-1" disabled={full || added || adding} onClick={() => onAdd(index, "good")}>
            Add as good
          </button>
          <button type="button" className="btn flex-1" disabled={full || added || adding} onClick={() => onAdd(index, "failure")}>
            Add as failure
          </button>
        </div>
      </div>
    </div>
  );
}
