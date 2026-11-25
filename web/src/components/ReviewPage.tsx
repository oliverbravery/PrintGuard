import { Flag } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { clock, day, framesLabel, FRAMES_PER_DAY, isDailyLimit, LIMIT_REASON, megabytes, printedAt, printsToReview, reviewable, sending, waitingMessage } from "../review";
import { useLazySnapshot } from "../snapshot";
import { useStore } from "../store";
import type { Monitor, ReviewFrame, ReviewSummary } from "../types";
import { Dialog } from "./Dialog";
import { DetailHead, ListHead, Page, Split } from "./Page";
import { RecordingScrubber } from "./RecordingScrubber";
import { ReviewList } from "./ReviewList";
import { SnapshotLightbox } from "./SnapshotLightbox";
import { Status } from "./Status";
import { TabPanel, Tabs } from "./Tabs";

function toggled(ids: Set<string>, id: string): Set<string> {
  const next = new Set(ids);
  if (!next.delete(id)) next.add(id);
  return next;
}

function flaggedWithItsStreak(ids: Set<string>, frames: ReviewFrame[], frame: ReviewFrame): Set<string> {
  const flagging = !ids.has(frame.id);
  const next = new Set(ids);
  for (const member of frames) {
    if (member.id !== frame.id && !(frame.kind === "alert" && member.alert === frame.id)) continue;
    if (flagging) next.add(member.id);
    else next.delete(member.id);
  }
  return next;
}

function verdict(frame: ReviewFrame, failure: boolean): string {
  if (frame.kind === "alert" || frame.kind === "streak") return failure ? "Real failure" : "False alarm";
  return failure ? "Failure" : "Good";
}

function picked(frame: ReviewFrame): string | null {
  if (frame.kind === "streak") return `${frame.streak} of ${frame.consecutive}`;
  return frame.kind === "added" || frame.kind === "spike" ? frame.kind : null;
}

function FrameCard({
  monitorId,
  frame,
  position,
  failure,
  onFlag,
  onRemove,
  onEnlarge,
}: {
  monitorId: string;
  frame: ReviewFrame;
  position: string;
  failure: boolean;
  onFlag: () => void;
  onRemove: () => void;
  onEnlarge: () => void;
}) {
  const { ref, url } = useLazySnapshot<HTMLLIElement>(monitorId, frame.id);
  const at = `${position.toLowerCase()} at ${clock(frame.ts)}`;
  return (
    <li ref={ref} className="relative border-b border-r border-line-0">
      <button type="button" className="block aspect-video w-full cursor-zoom-in bg-ink-1" aria-label={`Enlarge ${at}`} onClick={onEnlarge}>
        {url && <img src={url} alt="" className="h-full w-full object-contain" />}
      </button>
      <span className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-3 py-2 pr-12">
        <Status tone={failure ? "bad" : "ok"}>{verdict(frame, failure)}</Status>
        <span className="mono text-xs text-text-2">
          {[picked(frame), clock(frame.ts), `${(frame.score * 100).toFixed(0)}%`].filter(Boolean).join(" · ")}
        </span>
      </span>
      <button
        type="button"
        className={`absolute right-2 top-2 grid size-8 cursor-pointer place-items-center border pointer-coarse:size-11 ${
          failure ? "border-bad bg-bad text-on-bad" : "border-line-1 bg-ink-0 text-text-0 hover:border-bad hover:text-bad"
        }`}
        aria-pressed={failure}
        aria-label={`Something went wrong in ${at}`}
        title="Something went wrong in this frame"
        onClick={onFlag}
      >
        <Flag size={14} aria-hidden />
      </button>
      <button
        type="button"
        className="absolute bottom-0 right-0 grid size-11 cursor-pointer place-items-center border-l border-t border-line-0 text-lg hover:bg-bad hover:text-on-bad"
        aria-label={`Don't send ${at}`}
        onClick={onRemove}
      >
        ×
      </button>
    </li>
  );
}

function Progress({ review, onDone }: { review: ReviewSummary; onDone: () => void }) {
  const { send, retrying } = useStore(useShallow((s) => ({ send: s.send, retrying: s.isPending("review.retry", review.id) })));
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
        <button className="btn btn-primary" disabled={retrying} onClick={() => send({ cmd: "review.retry", id: review.id })}>
          Try now
        </button>
      </div>
    </div>
  );
}

type Column = "picked" | "scrubber";

function ReviewDetail({ monitor, review }: { monitor: Monitor; review: ReviewSummary }) {
  const navigate = useNavigate();
  const { switchedOff, send, submitting, deleting, fetchReview, detail, reconnecting } = useStore(
    useShallow((s) => ({
      switchedOff: s.engine?.settings.feedback === "off",
      send: s.send,
      submitting: s.isPending("review.send", review.id),
      deleting: s.isPending("review.delete", review.id),
      fetchReview: s.fetchReview,
      detail: s.reviewData[review.id],
      reconnecting: s.reconnecting,
    })),
  );
  const [flagged, setFlagged] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [ignoring, setIgnoring] = useState(false);
  const [enlarged, setEnlarged] = useState<ReviewFrame | null>(null);
  const [column, setColumn] = useState<Column>("picked");

  useEffect(() => {
    if (!reconnecting) fetchReview(review.id);
  }, [reconnecting, review.id, review.frames]);

  const loaded = detail?.frames;
  const frames = loaded ?? [];
  const kept = frames.filter((frame) => !removed.has(frame.id));
  const over = kept.length - FRAMES_PER_DAY;
  const showsFailure = (frame: ReviewFrame) => (frame.kind === "added" && frame.label === "failure") !== flagged.has(frame.id);
  const list = `/monitors/${monitor.id}/review`;
  const scrubber = detail && detail.timeline.length > 1 && !switchedOff;

  const submit = () =>
    send({
      cmd: "review.send",
      id: review.id,
      failures: kept.filter(showsFailure).map((frame) => frame.id),
      removed: [...removed],
    });

  const picked = (
    <section aria-label="Frames to send" className="flex min-h-0 flex-1 flex-col">
      <ListHead title="Frames to send">
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
      </ListHead>
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
      <ul className="relative grid min-h-0 flex-1 grid-cols-2 content-start overflow-y-auto xl:grid-cols-3">
        {kept.map((frame, index) => (
          <FrameCard
            key={frame.id}
            monitorId={monitor.id}
            frame={frame}
            position={`Frame ${index + 1} of ${kept.length}`}
            failure={showsFailure(frame)}
            onFlag={() => setFlagged((current) => flaggedWithItsStreak(current, frames, frame))}
            onRemove={() => setRemoved((current) => toggled(current, frame.id))}
            onEnlarge={() => setEnlarged(frame)}
          />
        ))}
      </ul>
    </section>
  );

  const workbench = (
    <section aria-label="Whole print recording" className="flex min-w-0 flex-col">
      <ListHead title="Whole print" />
      {scrubber ? (
        <RecordingScrubber review={detail} full={over >= 0} onAdd={(index, label) => send({ cmd: "review.add", id: review.id, index, label })} />
      ) : (
        <p className="px-4 py-4 text-sm text-text-2">{switchedOff ? "The end-of-print review is switched off in Settings." : "This print has no recording to scrub."}</p>
      )}
      <div className="border-t border-line-0 px-4 py-4">
        <details className="text-sm text-text-2">
          <summary className="cursor-pointer py-1 hover:text-text-1 pointer-coarse:py-3">What's sent</summary>
          <p className="mt-1.5 leading-relaxed">
            The frames shown here with the labels you gave them. With each frame goes its risk score, timestamp and why it
            was picked, the detection model and runtime that scored it, how many frames in a row were over the threshold,
            the printer's status and progress at the time and whether the camera was cropped. With each print goes a random
            ID for it and for each frame, this monitor's alert settings, what PrintGuard did on each alert and whether you
            resumed a print it paused, how the print ended, the printer integration type, the printer model (if set on the
            printer), the PrintGuard version and a random ID for this hub. No names or camera URLs are sent. The inbox sees your IP address like any web server does,
            and only keeps a keyed hash of it until the next day to enforce the daily limit. Frames are stored privately
            in the EU and used solely to train PrintGuard's detection models. To have yours deleted, open an issue on
            GitHub with the hub ID from Settings.
          </p>
        </details>
      </div>
    </section>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <DetailHead title={printedAt(review)} />
      {review.status === "running" && <p className="px-4 py-4 text-sm text-text-1">This print is still running. You can review it once it finishes.</p>}
      {(review.status === "queued" || review.status === "sent") && <Progress review={review} onDone={() => navigate(list)} />}
      {reviewable(review) && (
        <>
          <div className="space-y-1 border-b border-line-0 px-4 py-3 text-sm">
            <p className="text-text-1">
              Click the flag on any frame where something went wrong, or × to leave a frame out. Every frame you share helps me train the next detection model.
            </p>
            {review.recording && review.recording.expires !== null && (
              <p className="text-text-2">
                This print's recording is {megabytes(review.recording.bytes)} and is deleted on {day(review.recording.expires)}, or once you send or ignore it.{" "}
                <Link to="/settings/storage" className="text-accent underline">
                  Manage storage
                </Link>
              </p>
            )}
          </div>
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
          <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <TabPanel prefix="review" id="scrubber" className={`relative min-h-0 min-w-0 overflow-y-auto md:border-r md:border-rule ${column === "scrubber" ? "" : "max-md:hidden"}`}>
              {workbench}
            </TabPanel>
            <TabPanel prefix="review" id="picked" className={`flex min-h-0 min-w-0 flex-col ${column === "picked" ? "" : "max-md:hidden"}`}>
              {picked}
            </TabPanel>
          </div>
          {switchedOff && <p className="border-t border-line-0 px-4 py-3 text-sm text-text-2">The end-of-print review is switched off in Settings, so nothing can be sent.</p>}
          <div className="surface grid grid-cols-2 border-t border-rule pb-[env(safe-area-inset-bottom)]">
            {review.status === "ready" ? (
              <button className="cell-action" onClick={() => setIgnoring(true)}>
                Ignore
              </button>
            ) : (
              <span />
            )}
            <button className="cell-action cell-action-primary" disabled={switchedOff || kept.length === 0 || over > 0 || submitting} onClick={submit}>
              Send {framesLabel(loaded ? kept.length : review.frames)}
            </button>
          </div>
        </>
      )}
      {ignoring && (
        <Dialog title="Ignore this print?" onClose={() => setIgnoring(false)}>
          <div className="space-y-4">
            <p className="text-sm text-text-1">
              Ignoring this print permanently deletes its {framesLabel(review.frames)} and recording, freeing{" "}
              {megabytes(review.bytes + (review.recording?.bytes ?? 0))}.
            </p>
            <div className="flex justify-end gap-2">
              <button className="btn" onClick={() => setIgnoring(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                disabled={deleting}
                onClick={() => {
                  if (send({ cmd: "review.delete", id: review.id }) !== null) {
                    setIgnoring(false);
                    navigate(list);
                  }
                }}
              >
                Ignore
              </button>
            </div>
          </div>
        </Dialog>
      )}
      {enlarged && (
        <SnapshotLightbox snapshotId={enlarged.id} onClose={() => setEnlarged(null)} caption={`${clock(enlarged.ts)} · ${(enlarged.score * 100).toFixed(0)}%`} />
      )}
    </div>
  );
}

export function ReviewPage() {
  const { monitorId, reviewId } = useParams();
  const engine = useStore((s) => s.engine);
  const monitor = engine?.monitors.find((m) => m.id === monitorId);
  if (!monitor) return <Navigate to="/" replace />;
  const prints = printsToReview(engine?.reviews ?? [], monitor.id);
  const chosen = prints.find((print) => print.id === reviewId);
  if (reviewId && !chosen) return <Navigate to={`/monitors/${monitor.id}/review`} replace />;
  const selected = chosen ?? prints[0];
  return (
    <Page
      title={`${monitor.name} review`}
      back={{ to: `/monitors/${monitor.id}`, label: "Monitors" }}
      phoneBack={reviewId ? { to: `/monitors/${monitor.id}/review`, label: "Back" } : undefined}
      subview
    >
      <Split
        list={
          <>
            <ListHead title={`Prints · ${prints.length}`} />
            <ReviewList monitorId={monitor.id} selectedId={selected?.id} />
          </>
        }
        detail={
          selected ? (
            <ReviewDetail key={selected.id} monitor={monitor} review={selected} />
          ) : (
            <>
              <DetailHead title="Nothing to review" />
              <p className="px-4 py-4 text-sm text-text-2">Frames from finished prints show up here so you can label and send them if you'd like.</p>
            </>
          )
        }
        detailShown={Boolean(reviewId)}
      />
    </Page>
  );
}
