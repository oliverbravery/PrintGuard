import { marked } from "marked";
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

const PULL_COMMAND = "docker compose pull && docker compose up -d";

export function UpdateDialog() {
  const { engine, releases, send, isPending, openDialog } = useStore();
  const update = engine?.update ?? null;
  const checking = isPending("update.check");
  const current = engine?.version || update?.current;
  const available = update?.available ?? false;
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    send({ cmd: "update.releases" });
  }, [send]);

  const release = releases.find((entry) => entry.version === selected) ?? releases[0] ?? null;
  const date = release?.published_at ? new Date(release.published_at).toLocaleDateString() : null;

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
                {update && " is the latest version"}
              </>
            )}
          </span>
          <button className="btn whitespace-nowrap" disabled={checking} onClick={() => send({ cmd: "update.check" })}>
            {checking ? "Checking…" : "Check now"}
          </button>
        </div>

        {release && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <label className="label shrink-0" htmlFor="release-version">
                Changelog
              </label>
              <select
                id="release-version"
                className="field"
                value={release.version}
                onChange={(event) => setSelected(event.target.value)}
              >
                {releases.map((entry) => (
                  <option key={entry.version} value={entry.version}>
                    v{entry.version}
                    {entry.version === current ? " installed" : entry.version === update?.latest ? " latest" : ""}
                  </option>
                ))}
              </select>
              {date && <span className="label shrink-0">{date}</span>}
            </div>
            <div
              className="changelog max-h-[40vh] overflow-y-auto pr-1"
              dangerouslySetInnerHTML={{ __html: marked.parse(release.notes || "_No release notes._") as string }}
            />
            <a
              href={update?.releases_url ?? release.url}
              target="_blank"
              rel="noreferrer"
              className="text-[0.7rem] text-accent underline hover:opacity-80 inline-block"
            >
              All releases on GitHub ↗
            </a>
          </div>
        )}

        {available && (
          <div className="hairline pt-4 space-y-2">
            <span className="label block">Update the hub</span>
            {update!.download ? (
              <>
                <a className="btn btn-primary inline-block" href={update!.download} target="_blank" rel="noreferrer">
                  Download v{update!.latest}
                </a>
                <p className="text-[0.7rem] text-text-2">
                  Quit PrintGuard from the tray, replace the app with the downloaded one, and open it again.
                </p>
              </>
            ) : (
              <>
                <p className="text-[0.7rem] text-text-2">
                  Pull the new image and recreate the container where your compose file lives:
                </p>
                <div className="flex items-center gap-2">
                  <code className="mono text-[0.68rem] text-text-0 break-all flex-1">{PULL_COMMAND}</code>
                  <button className="btn" onClick={() => navigator.clipboard?.writeText(PULL_COMMAND)}>
                    Copy
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        <p className="text-[0.7rem] text-text-2">
          {update ? `Last checked ${new Date(update.checked_at * 1000).toLocaleString()}.` : "No check has run yet."}
        </p>
      </div>
    </Dialog>
  );
}
