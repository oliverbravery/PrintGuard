import { NewTab } from "./NewTab";

const ISSUES_URL = "https://github.com/oliverbravery/PrintGuard/issues";

export function ExperimentalBadge() {
  return (
    <div className="flex items-start gap-2">
      <span className="chip chip-warn mt-0.5">Experimental</span>
      <p className="text-[0.7rem] leading-snug text-text-2">
        This feature is new and may still be buggy. Please{" "}
        <a href={ISSUES_URL} target="_blank" rel="noreferrer" className="text-warn underline hover:text-accent">
          report any issues <NewTab />
        </a>
        .
      </p>
    </div>
  );
}
