const ISSUES_URL = "https://github.com/oliverbravery/PrintGuard/issues";
const SUMMARY = "This feature is new and may still be buggy.";

export function ExperimentalBadge({ detail = false }: { detail?: boolean }) {
  if (!detail) return <span className="chip chip-warn" title={SUMMARY}>Experimental</span>;
  return (
    <div className="flex items-start gap-2">
      <span className="chip chip-warn mt-0.5">Experimental</span>
      <p className="text-[0.7rem] leading-snug text-text-2">
        {SUMMARY} Please{" "}
        <a href={ISSUES_URL} target="_blank" rel="noreferrer" className="text-warn underline hover:text-accent">
          report any issues ↗
        </a>
        .
      </p>
    </div>
  );
}
