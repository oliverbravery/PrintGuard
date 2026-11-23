import { Link } from "react-router";
import { framesLabel, printedAt, printsToReview, statusText } from "../review";
import { useStore } from "../store";

export function ReviewList({ monitorId, selectedId }: { monitorId: string; selectedId?: string }) {
  const reviews = useStore((s) => s.engine?.reviews ?? []);
  const prints = printsToReview(reviews, monitorId);
  if (prints.length === 0) return <p className="px-4 py-3 text-sm text-text-2">No finished prints yet. PrintGuard keeps frames from each one for you to label and send.</p>;
  return (
    <ul>
      {prints.map((print) => (
        <li key={print.id}>
          <Link to={`/monitors/${monitorId}/review/${print.id}`} aria-current={print.id === selectedId ? "page" : undefined} className="list-row">
            <span className="min-w-0 flex-1">
              <span className="mono block truncate text-sm">{printedAt(print)}</span>
              <span className="mono block text-xs text-text-2">
                {framesLabel(print.frames)} · {statusText(print)}
              </span>
            </span>
            {print.status === "ready" && <span className="chip chip-accent">review</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
}
