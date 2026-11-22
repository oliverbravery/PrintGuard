import { day, megabytes } from "../review";
import { useStore } from "../store";
import { ConfirmButton, useConfirm } from "./ConfirmButton";
import { NewTab } from "./NewTab";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

const RECORDING_DAYS = [3, 7, 14];

export function StorageTab() {
  const { engine, send, updateSettings } = useStore();
  const reviews = engine?.reviews ?? [];
  const reviewing = engine?.settings.feedback !== "off";
  const recordingDays = engine?.settings.recording_days ?? 7;
  const waitingReviews = reviews.filter((review) => review.status === "ready" || review.status === "queued").length;
  const setReviewing = (on: boolean) => updateSettings({ feedback: on ? "ask" : "off" }, "storage");
  const stopReviewing = useConfirm(() => setReviewing(false));
  const recorded = reviews.filter((review) => review.recording);
  const recordingBytes = recorded.reduce((total, review) => total + review.recording!.bytes, 0);
  const keptBytes = reviews.reduce((total, review) => total + review.bytes, 0);
  const monitorName = (id: string) => engine?.monitors.find((monitor) => monitor.id === id)?.name ?? "Removed monitor";

  return (
    <div className="space-y-3">
      <Toggle
        label="Ask me to review frames after a print"
        on={reviewing}
        onChange={(on) => (on || waitingReviews === 0 ? setReviewing(on) : stopReviewing.press())}
      />
      <span className="block text-xs leading-relaxed text-text-2">
        <span role="status" className="block text-warn">
          {stopReviewing.armed &&
            `Press the switch again to turn it off. ${waitingReviews} ${waitingReviews === 1 ? "print" : "prints"} waiting for review will be dismissed.`}
        </span>
        {reviewing
          ? "PrintGuard keeps a few frames from each print locally so you can label them and send them to me to help train future detection models. Nothing ever leaves your hub unless you review a print and click Send. Turning this off deletes any frames kept so far."
          : "While this is off, PrintGuard only keeps alert snapshots for risk history. It won't prompt you to review prints and nothing is sent."}{" "}
        <a className="text-accent underline hover:opacity-80" href="https://github.com/oliverbravery/PrintGuard/blob/main/docs/feedback.md" target="_blank" rel="noreferrer">
          What's sent <NewTab />
        </a>
      </span>
      {reviewing && (
        <>
          <label className="label block pt-2" htmlFor="recording-days">
            Recordings
          </label>
          <select
            id="recording-days"
            className="field w-full"
            value={recordingDays}
            onChange={(event) => updateSettings({ recording_days: Number(event.target.value) }, "storage")}
          >
            <option value={0}>Don't record prints</option>
            {RECORDING_DAYS.map((days) => (
              <option key={days} value={days}>
                Keep each print's recording for {days} days
              </option>
            ))}
          </select>
          <span className="block text-xs leading-relaxed text-text-2">
            PrintGuard saves one frame every 5 seconds so you can scrub through a finished print and add frames it missed.
            Recordings are deleted automatically once you send or ignore the print. An 8-hour print uses about 100 MB.
          </span>
        </>
      )}
      <div className="grid grid-cols-2 gap-2 pt-2">
        <div className="border border-line-0 px-3 py-2">
          <span className="label block">Recordings</span>
          <span className="mono text-sm text-text-0">{megabytes(recordingBytes)}</span>
        </div>
        <div className="border border-line-0 px-3 py-2">
          <span className="label block">Kept frames</span>
          <span className="mono text-sm text-text-0">{megabytes(keptBytes)}</span>
        </div>
      </div>
      {recorded.length > 0 && (
        <ul className="divide-y divide-line-0 border border-line-0" aria-label="Recordings">
          {recorded.map((review) => (
            <li key={review.id} className="flex items-center gap-3 px-3 py-2">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-text-1">
                  {monitorName(review.monitor_id)} · {day(review.started)}
                </span>
                <span className="label block">
                  {review.recording!.expires === null ? "recording now" : `deleted ${day(review.recording!.expires)}`}
                  {review.status === "ready" && " · waiting for review"}
                </span>
              </span>
              <span className="mono text-xs text-text-2">{megabytes(review.recording!.bytes)}</span>
              <ConfirmButton aria-label={`Delete the recording of ${monitorName(review.monitor_id)} from ${day(review.started)}`} onConfirm={() => send({ cmd: "recording.delete", ids: [review.id] })}>
                Delete
              </ConfirmButton>
            </li>
          ))}
        </ul>
      )}
      {recorded.length > 1 && (
        <div className="flex justify-end">
          <ConfirmButton onConfirm={() => send({ cmd: "recording.delete", ids: recorded.map((review) => review.id) })}>Delete all recordings</ConfirmButton>
        </div>
      )}
      {engine?.feedback_hub && (
        <div className="flex items-center justify-between gap-3 border border-line-0 px-3 py-2">
          <span className="text-xs text-text-1">Hub ID</span>
          <span className="mono text-xs break-all text-text-2">{engine.feedback_hub}</span>
        </div>
      )}
      <div className="flex justify-end">
        <SaveStatus scope="settings:storage" />
      </div>
    </div>
  );
}
