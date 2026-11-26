import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { renderMarkdown } from "../markdown";
import { useStore } from "../store";
import { webUrl } from "../urls";
import { CopyButton } from "./CopyButton";
import { Dialog } from "./Dialog";
import { NewTab } from "./NewTab";

const PULL_COMMAND = "docker compose pull && docker compose up -d";

export function UpdateDialog() {
  const { engine, releases, reconnecting, send, checking, installing, openDialog, updateSettings } = useStore(
    useShallow((s) => ({
      engine: s.engine,
      releases: s.releases,
      reconnecting: s.reconnecting,
      send: s.send,
      checking: s.isPending("update.check"),
      installing: s.isPending("update.install"),
      openDialog: s.openDialog,
      updateSettings: s.updateSettings,
    })),
  );
  const update = engine?.update ?? null;
  const current = engine?.version || update?.current;
  const available = update?.available ?? false;
  const ready = update?.ready ?? null;
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!reconnecting) send({ cmd: "update.releases" });
  }, [reconnecting]);

  const release = releases.find((entry) => entry.version === selected) ?? releases[0] ?? null;
  const date = release?.published_at ? new Date(release.published_at).toLocaleDateString() : null;
  const releasesUrl = webUrl(update?.releases_url ?? release?.url ?? "");
  const downloadUrl = update?.download ? webUrl(update.download) : null;

  return (
    <Dialog title={available ? "Update available" : "Updates"} onClose={() => openDialog(null)}>
      <div className="space-y-5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-text-1">
            {available ? (
              <>
                <span className="mono text-text-2">v{update!.current}</span>
                <span className="text-text-2"> to </span>
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
              className="changelog max-h-[40dvh] overflow-y-auto pr-1"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(release.notes || "_No release notes._", { base: release.files_url }) }}
            />
            {releasesUrl && (
              <a
                href={releasesUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-accent underline hover:opacity-80 inline-block"
              >
                All releases on GitHub <NewTab />
              </a>
            )}
          </div>
        )}

        {available && (
          <div className="hairline pt-4 space-y-2">
            <span className="label block">Update the hub</span>
            {engine?.installs_updates && ready ? (
              <>
                <p className="text-sm text-text-1">
                  v{ready} is downloaded. Restart now to install it, or PrintGuard installs it by itself once no monitor
                  is watching a print.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button className="btn btn-primary" disabled={installing} onClick={() => send({ cmd: "update.install" })}>
                    {installing ? "Restarting…" : "Restart now"}
                  </button>
                  <button className="btn" onClick={() => openDialog(null)}>
                    Later
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      updateSettings({ skipped_version: ready }, "updates");
                      openDialog(null);
                    }}
                  >
                    Skip this version
                  </button>
                </div>
              </>
            ) : engine?.installs_updates ? (
              <>
                <button className="btn btn-primary" disabled={installing} onClick={() => send({ cmd: "update.install" })}>
                  {installing ? "Downloading…" : `Update to v${update!.latest}`}
                </button>
                <p className="text-xs text-text-2">PrintGuard downloads it, then restarts to install it.</p>
              </>
            ) : downloadUrl ? (
              <>
                <a className="btn btn-primary inline-block" href={downloadUrl} target="_blank" rel="noreferrer">
                  Download v{update!.latest} <NewTab />
                </a>
                <p className="text-xs text-text-2">
                  Quit PrintGuard from the menu bar or system tray, replace the app with the new download and open it again.
                </p>
              </>
            ) : (
              <>
                <p className="text-xs text-text-2">
                  Pull the new image and recreate the container from the folder with your compose file:
                </p>
                <div className="flex items-center gap-2">
                  <code className="mono text-xs text-text-0 break-all flex-1">{PULL_COMMAND}</code>
                  <CopyButton text={PULL_COMMAND} />
                </div>
              </>
            )}
          </div>
        )}

        <p className="text-xs text-text-2">
          {update ? `Last checked ${new Date(update.checked_at * 1000).toLocaleString()}.` : "No check has run yet."}
        </p>
      </div>
    </Dialog>
  );
}
