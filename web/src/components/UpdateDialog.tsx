import { marked } from "marked";
import { useStore } from "../store";
import type { UpdateRelease } from "../types";
import { Dialog } from "./Dialog";

const PULL_COMMAND = "docker compose pull && docker compose up -d";

function ReleaseNotes({ release }: { release: UpdateRelease }) {
  const date = release.published_at ? new Date(release.published_at).toLocaleDateString() : null;
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <a
          href={release.url}
          target="_blank"
          rel="noreferrer"
          className="display text-sm font-semibold text-text-1 hover:text-accent"
        >
          v{release.version}
        </a>
        {date && <span className="label">{date}</span>}
      </div>
      <div
        className="changelog"
        dangerouslySetInnerHTML={{ __html: marked.parse(release.notes || "_No release notes._") as string }}
      />
    </div>
  );
}

export function UpdateDialog() {
  const { engine, send, isPending, openDialog } = useStore();
  const update = engine?.update ?? null;
  const checking = isPending("update.check");
  const current = engine?.version || update?.current;
  const available = update?.available ?? false;

  return (
    <Dialog title={available ? "Update available" : "Updates"} onClose={() => openDialog(null)}>
      <div className="space-y-5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-text-1">
            {available ? (
              <>
                <span className="mono text-text-2">v{update!.current}</span>
                <span className="text-text-2"> → </span>
                <span className="mono text-accent">v{update!.latest}</span>
              </>
            ) : (
              <>
                Running <span className="mono text-accent">v{current}</span>
                {update && " — the latest version"}
              </>
            )}
          </span>
          <button className="btn whitespace-nowrap" disabled={checking} onClick={() => send({ cmd: "update.check" })}>
            {checking ? "Checking…" : "Check now"}
          </button>
        </div>

        {available && (
          <>
            <div className="space-y-5 max-h-[45vh] overflow-y-auto pr-1">
              {update!.releases.map((release) => (
                <ReleaseNotes key={release.version} release={release} />
              ))}
            </div>
            <div className="hairline pt-4 space-y-2">
              <span className="label block">Update the hub</span>
              <p className="text-[0.7rem] text-text-2">
                Pull the new image and recreate the container where your compose file lives:
              </p>
              <div className="flex items-center gap-2">
                <code className="mono text-[0.68rem] text-text-0 break-all flex-1">{PULL_COMMAND}</code>
                <button className="btn" onClick={() => navigator.clipboard?.writeText(PULL_COMMAND)}>
                  Copy
                </button>
              </div>
              <a
                href={update!.releases_url}
                target="_blank"
                rel="noreferrer"
                className="text-[0.7rem] text-accent underline hover:opacity-80 inline-block"
              >
                View all releases on GitHub ↗
              </a>
            </div>
          </>
        )}

        {!available && (
          <p className="text-[0.7rem] text-text-2">
            {update ? `Last checked ${new Date(update.checked_at * 1000).toLocaleString()}.` : "No check has run yet."}
          </p>
        )}
      </div>
    </Dialog>
  );
}
