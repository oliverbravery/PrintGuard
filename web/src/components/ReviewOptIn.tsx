import { Flag } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { NewTab } from "./NewTab";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

const FEEDBACK_DOCS = "https://github.com/oliverbravery/PrintGuard/blob/main/docs/feedback.md";

export function ReviewOptIn() {
  const { reviewing, updateSettings } = useStore(
    useShallow((s) => ({
      reviewing: s.engine?.settings.feedback !== "off",
      updateSettings: s.updateSettings,
    })),
  );

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-line-0 border border-line-0">
        <li className="flex gap-3 px-3.5 py-2.5">
          <span aria-hidden className="mt-0.5 grid size-7 shrink-0 place-items-center border border-bad bg-bad text-on-bad">
            <Flag size={13} />
          </span>
          <div className="min-w-0">
            <div className="text-sm text-text-0">Flag frames where something went wrong</div>
            <div className="text-xs leading-relaxed text-text-2">
              Alert frames start as False alarm and flip to Real failure when you flag them. Other frames start as Good
              and flip to Failure.
            </div>
          </div>
        </li>
        <li className="flex gap-3 px-3.5 py-2.5">
          <span aria-hidden className="mt-0.5 grid size-7 shrink-0 place-items-center border border-line-1 bg-ink-0 text-base leading-none text-text-0">
            ×
          </span>
          <div className="min-w-0">
            <div className="text-sm text-text-0">Drop frames or add missed ones</div>
            <div className="text-xs leading-relaxed text-text-2">
              Press × to leave out any frame you'd rather not share, or scrub the print's recording to add moments
              PrintGuard missed. Press Send when you're ready, or Ignore to delete them.
            </div>
          </div>
        </li>
      </ul>
      <div className="space-y-2 border border-line-0 px-3.5 py-3">
        <Toggle
          label="Ask me to review frames after a print"
          on={reviewing}
          onChange={(on) => updateSettings({ feedback: on ? "ask" : "off" }, "review")}
        />
        <p className="text-xs leading-relaxed text-text-2">
          {reviewing
            ? "PrintGuard will keep frames and a short recording after each print so you can review them. You can switch this off any time under Settings, in Storage."
            : "PrintGuard will only keep alert snapshots for risk history and won't prompt you to review prints. You can turn this back on under Settings, in Storage."}{" "}
          <a className="text-accent underline hover:opacity-80" href={FEEDBACK_DOCS} target="_blank" rel="noreferrer">
            What's sent <NewTab />
          </a>
        </p>
        <div className="flex justify-end empty:hidden">
          <SaveStatus scope="settings:review" />
        </div>
      </div>
    </div>
  );
}
