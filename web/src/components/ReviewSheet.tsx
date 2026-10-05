import { useEffect, useState } from "react";
import { clock, isDailyLimit, LIMIT_REASON, sending, waitingMessage } from "../review";
import { useStore } from "../store";
import type { Monitor, ReviewFrame, ReviewSummary } from "../types";
import { Sheet } from "./Dialog";

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
  failure,
  removed,
  onToggle,
  onRemove,
}: {
  monitorId: string;
  frame: ReviewFrame;
  failure: boolean;
  removed: boolean;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const url = useStore((s) => s.snapshotCache[frame.id]);
  const fetchSnapshot = useStore((s) => s.fetchSnapshot);
  useEffect(() => {
    fetchSnapshot(monitorId, frame.id);
  }, [monitorId, frame.id]);
  const label = verdict(frame, failure);
  return (
    <div className={`panel relative overflow-hidden ${failure && !removed ? "!border-bad" : ""}`}>
      <button
        type="button"
        className={`block w-full text-left ${removed ? "opacity-40" : "cursor-pointer"}`}
        aria-pressed={failure}
        aria-label={`Frame at ${clock(frame.ts)}, marked ${label}. Press to change`}
        disabled={removed}
        onClick={onToggle}
      >
        <div className="aspect-video bg-ink-0">{url && <img src={url} alt="" className="h-full w-full object-cover" />}</div>
        <span className="flex items-center justify-between gap-2 px-2 py-1.5">
          <span className={`chip ${failure ? "chip-bad" : "chip-ok"}`}>{label}</span>
          <span className="label">
            {clock(frame.ts)} · {(frame.score * 100).toFixed(0)}%
          </span>
        </span>
      </button>
      <button
        type="button"
        className="btn absolute right-1 top-1 !bg-ink-1 !px-2 !py-0.5"
        aria-label={`${removed ? "Send" : "Don't send"} the frame at ${clock(frame.ts)}`}
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
        <p className="text-sm text-text-1">Sent {review.sent} frames. Thank you.</p>
        <button className="btn btn-primary w-full" onClick={onClose}>
          Done
        </button>
      </div>
    );
  if (sending(review))
    return (
      <p className="px-5 py-4 text-sm text-text-1" role="status">
        Sending {review.sent} of {review.chosen} frames…
      </p>
    );
  return (
    <div className="space-y-3 px-5 py-4">
      {review.sent > 0 && (
        <p className="text-sm text-text-1">
          Sent {review.sent} of {review.chosen} frames.
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
  const { send, isPending, openReview, fetchReview, reviewData, reconnecting } = useStore();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [relabelled, setRelabelled] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [printer, setPrinter] = useState("");
  const frames = reviewData[review.id]?.frames ?? [];
  const kept = frames.filter((frame) => !removed.has(frame.id));
  const showsFailure = (frame: ReviewFrame) => (outcome === "failed" && frame.kind === "alert") !== relabelled.has(frame.id);
  const close = () => openReview(null);

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
            PrintGuard kept {review.frames} frames from this print. Label them and send them to me, and I'll use them to train the detection model.
          </p>
          <div>
            <span className="label mb-2 block">Did this print finish fine?</span>
            <div className="flex gap-2">
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
                  ? "Press every frame where you can see the failure. Use the × to leave a frame out, and Undo to put it back."
                  : "Every frame is marked good. Press one to change it, or use the × to leave it out and Undo to put it back."}
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {frames.map((frame) => (
                  <FrameCard
                    key={frame.id}
                    monitorId={monitor.id}
                    frame={frame}
                    failure={showsFailure(frame)}
                    removed={removed.has(frame.id)}
                    onToggle={() => setRelabelled((current) => toggled(current, frame.id))}
                    onRemove={() => setRemoved((current) => toggled(current, frame.id))}
                  />
                ))}
              </div>
              <input
                className="field"
                placeholder="Printer model (optional), such as Prusa MK4"
                maxLength={80}
                value={printer}
                onChange={(event) => setPrinter(event.target.value)}
              />
              <details className="text-[0.7rem] text-text-2">
                <summary className="cursor-pointer hover:text-text-1">What's sent</summary>
                <p className="mt-1.5 leading-relaxed">
                  The frames shown here with the labels you gave them, each frame's risk score and time, this monitor's alert
                  threshold, the type of printer connection, the printer model if you type one, the PrintGuard version and a
                  random ID for this hub. No names or camera URLs. The inbox sees your IP address, as any server does, and keeps
                  only a hash of it until the next day for the daily limit. Frames are stored privately in the EU and used
                  only to train PrintGuard's detection model. To have yours deleted, raise an issue on GitHub with the hub ID from Settings.
                </p>
              </details>
            </>
          )}
          <div className="flex gap-2">
            {review.status === "ready" && (
              <button className="btn flex-1" onClick={() => (send({ cmd: "review.dismiss", id: review.id }), close())}>
                Not this print
              </button>
            )}
            <button className="btn btn-primary flex-1" disabled={!outcome || kept.length === 0 || isPending("review.send")} onClick={submit}>
              Send {kept.length} frames
            </button>
          </div>
        </div>
      )}
    </Sheet>
  );
}
