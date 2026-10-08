import { Maximize2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { clock, framesLabel, isDailyLimit, LIMIT_REASON, sending, waitingMessage } from "../review";
import { useLazySnapshot } from "../snapshot";
import { useStore } from "../store";
import type { Monitor, ReviewFrame, ReviewSummary } from "../types";
import { Sheet } from "./Dialog";
import { SnapshotLightbox } from "./SnapshotLightbox";

type Outcome = "fine" | "failed";

function toggled(ids: Set<string>, id: string): Set<string> {
  const next = new Set(ids);
  if (!next.delete(id)) next.add(id);
  return next;
}

function verdict(frame: ReviewFrame, failure: boolean): string {
  if (frame.kind === "alert") return failure ? "Real failure" : "False alarm";
  return failure ? "Failure" : "Good";
}

function FrameCard({
  monitorId,
  frame,
  position,
  failure,
  removed,
  onToggle,
  onRemove,
  onEnlarge,
}: {
  monitorId: string;
  frame: ReviewFrame;
  position: string;
  failure: boolean;
  removed: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onEnlarge: () => void;
}) {
  const { ref, url } = useLazySnapshot<HTMLDivElement>(monitorId, frame.id);
  const label = verdict(frame, failure);
  return (
    <div ref={ref} className={`panel relative overflow-hidden ${failure && !removed ? "!border-bad" : ""}`}>
      <button
        type="button"
        className={`block w-full text-left ${removed ? "opacity-40" : "cursor-pointer"}`}
        aria-pressed={failure}
        aria-label={`${position} at ${clock(frame.ts)}, marked ${label}. Press to change`}
        disabled={removed}
        onClick={onToggle}
      >
        <div className="aspect-video bg-ink-0">{url && <img src={url} alt="" className="h-full w-full object-contain" />}</div>
        <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-2 py-1.5">
          <span className={`chip ${failure ? "chip-bad" : "chip-ok"}`}>{label}</span>
          <span className="label ml-auto">
            {clock(frame.ts)} · {(frame.score * 100).toFixed(0)}%
          </span>
        </span>
      </button>
      <button
        type="button"
        className="btn absolute left-1 top-1 !bg-ink-1 !px-2 !py-1"
        aria-label={`Enlarge ${position.toLowerCase()} at ${clock(frame.ts)}`}
        onClick={onEnlarge}
      >
        <Maximize2 size={14} aria-hidden />
      </button>
      <button
        type="button"
        className="btn absolute right-1 top-1 !bg-ink-1 !px-2 !py-0.5"
        aria-label={`${removed ? "Send" : "Don't send"} ${position.toLowerCase()} at ${clock(frame.ts)}`}
        onClick={onRemove}
      >
        {removed ? "Undo" : "×"}
      </button>
    </div>
  );
}

function Progress({ review, onClose }: { review: ReviewSummary; onClose: () => void }) {
  const { send, isPending } = useStore();
  if (review.status === "sent")
    return (
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-text-1">Sent {framesLabel(review.sent)}. Thank you.</p>
        <button className="btn btn-primary w-full" onClick={onClose}>
          Done
        </button>
      </div>
    );
  if (sending(review))
    return (
      <p className="px-5 py-4 text-sm text-text-1" role="status">
        Sending {review.sent} of {framesLabel(review.chosen)}…
      </p>
    );
  return (
    <div className="space-y-3 px-5 py-4">
      {review.sent > 0 && (
        <p className="text-sm text-text-1">
          Sent {review.sent} of {framesLabel(review.chosen)}.
        </p>
      )}
      <p className="text-sm text-text-1" role="status">
        {waitingMessage(review)}
      </p>
      {isDailyLimit(review.code) && <p className="text-[0.7rem] leading-relaxed text-text-2">{LIMIT_REASON}</p>}
      <div className="flex gap-2">
        <button className="btn flex-1" onClick={() => send({ cmd: "review.dismiss", id: review.id })}>
          Cancel sending
        </button>
        <button className="btn btn-primary flex-1" disabled={isPending("review.retry")} onClick={() => send({ cmd: "review.retry", id: review.id })}>
          Try now
        </button>
      </div>
    </div>
  );
}

export function ReviewSheet({ review, monitor }: { review: ReviewSummary; monitor: Monitor }) {
  const { engine, send, isPending, openReview, fetchReview, reviewData, reconnecting } = useStore();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [relabelled, setRelabelled] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [printer, setPrinter] = useState("");
  const [enlarged, setEnlarged] = useState<ReviewFrame | null>(null);
  const loaded = reviewData[review.id]?.frames;
  const frames = loaded ?? [];
  const switchedOff = engine?.settings.feedback === "off";
  const kept = frames.filter((frame) => !removed.has(frame.id));
  const showsFailure = (frame: ReviewFrame) => (outcome === "failed" && frame.kind === "alert") !== relabelled.has(frame.id);
  const close = () => openReview(null);
  const outcomeLabelId = useId();

  useEffect(() => {
    if (!reconnecting) fetchReview(review.id);
  }, [reconnecting, review.id, review.frames]);

  const answer = (next: Outcome) => {
    setOutcome(next);
    setRelabelled(new Set());
  };

  const submit = () =>
    send({
      cmd: "review.send",
      id: review.id,
      failures: kept.filter(showsFailure).map((frame) => frame.id),
      removed: [...removed],
      printer: printer.trim(),
    });

  return (
    <Sheet title={`${monitor.name} · review`} onClose={close} closeLabel="Close print review" width="sm:w-[680px]">
      {review.status === "running" && <p className="px-5 py-4 text-sm text-text-1">This print is still running. You can review it once it ends.</p>}
      {(review.status === "queued" || review.status === "sent") && <Progress review={review} onClose={close} />}
      {(review.status === "ready" || review.status === "dismissed") && (
        <div className="space-y-4 px-5 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
          <p className="text-sm text-text-1">
            PrintGuard kept {framesLabel(review.frames)} from this print. Label them and send them to me, and I'll use them to train the detection model.
          </p>
          <div>
            <span id={outcomeLabelId} className="label mb-2 block">
              Did this print finish fine?
            </span>
            <div role="group" aria-labelledby={outcomeLabelId} className="flex gap-2">
              <button className={`btn flex-1 ${outcome === "fine" ? "!border-accent !text-accent" : ""}`} aria-pressed={outcome === "fine"} onClick={() => answer("fine")}>
                Yes
              </button>
              <button className={`btn flex-1 ${outcome === "failed" ? "!border-accent !text-accent" : ""}`} aria-pressed={outcome === "failed"} onClick={() => answer("failed")}>
                No, it failed
              </button>
            </div>
          </div>
          {outcome && (
            <>
              <p className="text-[0.7rem] leading-relaxed text-text-2">
                {outcome === "failed"
                  ? "Alert frames are marked as real failures. Press a frame to change its label. Use the × to leave one out, and Undo to put it back."
                  : "Every frame is marked good. Press one to change it, or use the × to leave it out and Undo to put it back."}
              </p>
              {!loaded && (
                <p role="status" className="mono text-[0.7rem] text-text-2">
                  loading the frames
                </p>
              )}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {frames.map((frame, index) => (
                  <FrameCard
                    key={frame.id}
                    monitorId={monitor.id}
                    frame={frame}
                    position={`Frame ${index + 1} of ${frames.length}`}
                    failure={showsFailure(frame)}
                    removed={removed.has(frame.id)}
                    onToggle={() => setRelabelled((current) => toggled(current, frame.id))}
                    onRemove={() => setRemoved((current) => toggled(current, frame.id))}
                    onEnlarge={() => setEnlarged(frame)}
                  />
                ))}
              </div>
              <input
                className="field"
                aria-label="Printer model"
                placeholder="Printer model (optional), such as Prusa MK4"
                maxLength={80}
                value={printer}
                onChange={(event) => setPrinter(event.target.value)}
              />
              <details className="text-[0.7rem] text-text-2">
                <summary className="cursor-pointer pointer-coarse:py-3.5 hover:text-text-1">What's sent</summary>
                <p className="mt-1.5 leading-relaxed">
                  The frames shown here with the labels you gave them, each frame's risk score, time and whether it was an
                  alert, a near miss or an ordinary frame, a random ID for the print and for each frame, this monitor's alert
                  threshold, the type of printer connection, the printer model if you type one, the PrintGuard version and a
                  random ID for this hub. No names or camera URLs. The inbox sees your IP address, as any server does, and keeps
                  only a hash of it until the next day for the daily limit. Frames are stored privately in the EU and used
                  only to train PrintGuard's detection model. To have yours deleted, raise an issue on GitHub with the hub ID from Settings.
                </p>
              </details>
            </>
          )}
          {switchedOff && <p className="text-[0.7rem] leading-relaxed text-text-2">The end-of-print review is switched off in Settings, so nothing can be sent.</p>}
          <div className="flex gap-2">
            {review.status === "ready" && (
              <button className="btn flex-1" onClick={() => (send({ cmd: "review.dismiss", id: review.id }), close())}>
                Not this print
              </button>
            )}
            <button className="btn btn-primary flex-1" disabled={switchedOff || !outcome || kept.length === 0 || isPending("review.send")} onClick={submit}>
              Send {framesLabel(loaded ? kept.length : review.frames)}
            </button>
          </div>
        </div>
      )}
      {enlarged && (
        <SnapshotLightbox
          snapshotId={enlarged.id}
          onClose={() => setEnlarged(null)}
          caption={`${clock(enlarged.ts)} · ${(enlarged.score * 100).toFixed(0)}%`}
        />
      )}
    </Sheet>
  );
}
