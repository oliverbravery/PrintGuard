import { Maximize2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { clock, day, framesLabel, FRAMES_PER_DAY, isDailyLimit, LIMIT_REASON, megabytes, reviewable, sending, waitingMessage } from "../review";
import { useLazySnapshot } from "../snapshot";
import { useStore } from "../store";
import type { ReviewFrame, ReviewSummary } from "../types";
import { Page } from "./Page";
import { RecordingScrubber } from "./RecordingScrubber";
import { Segmented } from "./Segmented";
import { SnapshotLightbox } from "./SnapshotLightbox";
import { Status } from "./Status";
import { TabPanel, Tabs } from "./Tabs";

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
  onToggle,
  onRemove,
  onEnlarge,
}: {
  monitorId: string;
  frame: ReviewFrame;
  position: string;
  failure: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onEnlarge: () => void;
}) {
  const { ref, url } = useLazySnapshot<HTMLLIElement>(monitorId, frame.id);
  const label = verdict(frame, failure);
  return (
    <li ref={ref} className="relative border-b border-r border-line-0">
      <button
        type="button"
        className="block w-full cursor-pointer text-left hover:bg-ink-1"
        aria-pressed={failure}
        aria-label={`${position} at ${clock(frame.ts)}, marked ${label}. Press to change`}
        onClick={onToggle}
      >
        <span className="block aspect-video bg-ink-1">{url && <img src={url} alt="" className="h-full w-full object-contain" />}</span>
        <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-3 py-2 pr-12">
          <Status tone={failure ? "bad" : "ok"}>{label}</Status>
          <span className="mono text-xs text-text-2">
            {frame.kind === "added" && "added · "}
            {clock(frame.ts)} · {(frame.score * 100).toFixed(0)}%
          </span>
        </span>
      </button>
      <button
        type="button"
        className="btn-inline absolute left-2 top-2"
        aria-label={`Enlarge ${position.toLowerCase()} at ${clock(frame.ts)}`}
        onClick={onEnlarge}
      >
        <Maximize2 size={14} aria-hidden />
      </button>
      <button
        type="button"
        className="absolute bottom-0 right-0 grid size-11 cursor-pointer place-items-center border-l border-t border-line-0 text-lg hover:bg-bad hover:text-on-bad"
        aria-label={`Don't send ${position.toLowerCase()} at ${clock(frame.ts)}`}
        onClick={onRemove}
      >
        ×
      </button>
    </li>
  );
}

function Progress({ review, onDone }: { review: ReviewSummary; onDone: () => void }) {
  const { send, isPending } = useStore();
  if (review.status === "sent")
    return (
      <div className="space-y-4 px-4 py-4">
        <p className="text-sm text-text-1">Sent {framesLabel(review.sent)}. Thank you.</p>
        <button className="btn btn-primary" onClick={onDone}>
          Done
        </button>
      </div>
    );
  if (sending(review))
    return (
      <p className="px-4 py-4 text-sm text-text-1" role="status">
        Sending {review.sent} of {framesLabel(review.chosen)}…
      </p>
    );
  return (
    <div className="space-y-3 px-4 py-4">
      {review.sent > 0 && (
        <p className="text-sm text-text-1">
          Sent {review.sent} of {framesLabel(review.chosen)}.
        </p>
      )}
      <p className="text-sm text-text-1" role="status">
        {waitingMessage(review)}
      </p>
      {isDailyLimit(review.code) && <p className="text-sm text-text-2">{LIMIT_REASON}</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn" onClick={() => send({ cmd: "review.dismiss", id: review.id })}>
          Cancel sending
        </button>
        <button className="btn btn-primary" disabled={isPending("review.retry")} onClick={() => send({ cmd: "review.retry", id: review.id })}>
          Try now
        </button>
      </div>
    </div>
  );
}

type Column = "picked" | "scrubber";

export function ReviewPage() {
  const { monitorId, reviewId } = useParams();
  const navigate = useNavigate();
  const { engine, send, isPending, fetchReview, reviewData, reconnecting } = useStore();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [relabelled, setRelabelled] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [printer, setPrinter] = useState("");
  const [enlarged, setEnlarged] = useState<ReviewFrame | null>(null);
  const [column, setColumn] = useState<Column>("picked");
  const monitor = engine?.monitors.find((m) => m.id === monitorId);
  const review = engine?.reviews.find((r) => r.id === reviewId && r.monitor_id === monitorId);

  useEffect(() => {
    if (!reconnecting && review) fetchReview(review.id);
  }, [reconnecting, review?.id, review?.frames]);

  if (!monitor || !review) return <Navigate to={monitor ? `/monitors/${monitor.id}` : "/"} replace />;
  const detail = reviewData[review.id];
  const loaded = detail?.frames;
  const frames = loaded ?? [];
  const switchedOff = engine?.settings.feedback === "off";
  const kept = frames.filter((frame) => !removed.has(frame.id));
  const over = kept.length - FRAMES_PER_DAY;
  const pickedByDefault = (frame: ReviewFrame) => (frame.kind === "added" ? frame.label === "failure" : outcome === "failed" && frame.kind === "alert");
  const showsFailure = (frame: ReviewFrame) => pickedByDefault(frame) !== relabelled.has(frame.id);
  const back = `/monitors/${monitor.id}`;
  const scrubber = detail && detail.timeline.length > 1 && !switchedOff;

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

  const picked = (
    <section aria-label="Frames to send" className="flex min-w-0 flex-col">
      <div className="flex min-h-11 flex-wrap items-center gap-3 border-b border-rule bg-ink-1 px-4 py-1.5">
        <span className="label flex-1 text-text-1">Frames to send</span>
        {loaded && (
          <span className={`mono text-sm font-semibold ${over > 0 ? "text-warn" : ""}`}>
            {kept.length} of {FRAMES_PER_DAY}
          </span>
        )}
        {kept.length > 1 && (
          <button className="btn-inline" onClick={() => setRemoved(new Set(frames.map((frame) => frame.id)))}>
            Clear all
          </button>
        )}
      </div>
      {loaded && (
        <div aria-hidden className="h-1 bg-line-0">
          <div className={`h-full ${over > 0 ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(100, (kept.length / FRAMES_PER_DAY) * 100)}%` }} />
        </div>
      )}
      {loaded && over >= 0 && (
        <p role="status" className="border-b border-line-0 px-4 py-2 text-sm text-warn">
          {over > 0 ? `You can send ${FRAMES_PER_DAY} frames a day. Leave ${over} out to send this print.` : `You can send ${FRAMES_PER_DAY} frames a day. Leave one out to add another.`}
        </p>
      )}
      {!loaded && (
        <p role="status" className="mono px-4 py-3 text-xs text-text-2">
          loading the frames
        </p>
      )}
      {loaded && kept.length === 0 && <p className="px-4 py-6 text-sm text-text-2">No frames picked. Add some from the recording.</p>}
      <ul className="grid grid-cols-2 xl:grid-cols-3">
        {kept.map((frame, index) => (
          <FrameCard
            key={frame.id}
            monitorId={monitor.id}
            frame={frame}
            position={`Frame ${index + 1} of ${kept.length}`}
            failure={showsFailure(frame)}
            onToggle={() => setRelabelled((current) => toggled(current, frame.id))}
            onRemove={() => setRemoved((current) => toggled(current, frame.id))}
            onEnlarge={() => setEnlarged(frame)}
          />
        ))}
      </ul>
    </section>
  );

  const workbench = (
    <section aria-label="Whole print recording" className="flex min-w-0 flex-col">
      <div className="flex min-h-11 items-center border-b border-rule bg-ink-1 px-4 py-1.5">
        <span className="label text-text-1">Whole print</span>
      </div>
      {scrubber ? (
        <RecordingScrubber review={detail} full={over >= 0} onAdd={(index, label) => send({ cmd: "review.add", id: review.id, index, label })} />
      ) : (
        <p className="px-4 py-4 text-sm text-text-2">{switchedOff ? "The end-of-print review is switched off in Settings." : "This print has no recording to scrub."}</p>
      )}
      <div className="space-y-3 border-t border-line-0 px-4 py-4">
        <label className="block">
          <span className="label mb-1 block">Printer model</span>
          <input
            className="field"
            placeholder="Optional, such as Prusa MK4"
            maxLength={80}
            value={printer}
            onChange={(event) => setPrinter(event.target.value)}
          />
        </label>
        <details className="text-sm text-text-2">
          <summary className="cursor-pointer py-1 hover:text-text-1 pointer-coarse:py-3">What's sent</summary>
          <p className="mt-1.5 leading-relaxed">
            The frames shown here with the labels you gave them, each frame's risk score, time and whether it was an alert, a near miss
            or an ordinary frame, a random ID for the print and for each frame, this monitor's alert threshold, the type of printer
            connection, the printer model if you type one, the PrintGuard version and a random ID for this hub. No names or camera URLs.
            The inbox sees your IP address, as any server does, and keeps only a hash of it until the next day for the daily limit.
            Frames are stored privately in the EU and used only to train PrintGuard's detection model. To have yours deleted, raise an
            issue on GitHub with the hub ID from Settings.
          </p>
        </details>
      </div>
    </section>
  );

  return (
    <Page title={`${monitor.name} review`} back={{ to: back, label: "Monitors" }} subview>
      {review.status === "running" && <p className="px-4 py-4 text-sm text-text-1">This print is still running. You can review it once it ends.</p>}
      {(review.status === "queued" || review.status === "sent") && <Progress review={review} onDone={() => navigate(back)} />}
      {reviewable(review) && (
        <>
          <div className="grid gap-3 border-b border-rule px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <div className="space-y-1 text-sm">
              <p className="text-text-1">
                PrintGuard kept {framesLabel(review.frames)} from this print. Label them and send them to me, and I'll use them to train the detection model.
              </p>
              {review.recording && review.recording.expires !== null && (
                <p className="text-text-2">
                  This print's recording is {megabytes(review.recording.bytes)} and is deleted on {day(review.recording.expires)}, or once you send or skip it.{" "}
                  <Link to="/settings/storage" className="text-accent underline">
                    Manage storage
                  </Link>
                </p>
              )}
            </div>
            <Segmented
              label="Did this print finish without any problems?"
              options={[
                { value: "fine", label: "Yes" },
                { value: "failed", label: "No, something went wrong" },
              ]}
              value={outcome}
              onChange={answer}
            />
          </div>
          {outcome && (
            <>
              <p className="border-b border-line-0 px-4 py-2 text-sm text-text-2">
                {outcome === "failed"
                  ? "Alert frames are marked as real failures. Press a frame to change its label, or use the × to leave it out."
                  : "Every frame PrintGuard picked is marked good. Press one to change it, or use the × to leave it out."}
              </p>
              <div className="md:hidden">
                <Tabs
                  prefix="review"
                  label="Review sections"
                  cells
                  tabs={[
                    { id: "picked", label: `Picked · ${kept.length}` },
                    { id: "scrubber", label: "Recording" },
                  ]}
                  value={column}
                  onChange={setColumn}
                />
              </div>
              <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                <TabPanel prefix="review" id="scrubber" className={`min-w-0 md:border-r md:border-rule ${column === "scrubber" ? "" : "max-md:hidden"}`}>
                  {workbench}
                </TabPanel>
                <TabPanel prefix="review" id="picked" className={`min-w-0 ${column === "picked" ? "" : "max-md:hidden"}`}>
                  {picked}
                </TabPanel>
              </div>
            </>
          )}
          {switchedOff && <p className="px-4 py-3 text-sm text-text-2">The end-of-print review is switched off in Settings, so nothing can be sent.</p>}
          <div className="surface sticky bottom-0 z-10 grid grid-cols-2 border-t border-rule pb-[env(safe-area-inset-bottom)]">
            {review.status === "ready" ? (
              <button
                className="cell-action"
                onClick={() => {
                  send({ cmd: "review.dismiss", id: review.id });
                  navigate(back);
                }}
              >
                Not this print
              </button>
            ) : (
              <span />
            )}
            <button
              className="cell-action cell-action-primary"
              disabled={switchedOff || !outcome || kept.length === 0 || over > 0 || isPending("review.send")}
              onClick={submit}
            >
              Send {framesLabel(loaded ? kept.length : review.frames)}
            </button>
          </div>
        </>
      )}
      {enlarged && (
        <SnapshotLightbox snapshotId={enlarged.id} onClose={() => setEnlarged(null)} caption={`${clock(enlarged.ts)} · ${(enlarged.score * 100).toFixed(0)}%`} />
      )}
    </Page>
  );
}
