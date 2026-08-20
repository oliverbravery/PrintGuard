import { useEffect, useRef, useState } from "react";
import { runsHere } from "../plugins";
import { useStore } from "../store";
import type { CatalogueEntry, Permission, PluginRecord } from "../types";
import { ConsentDialog, PermissionList } from "./PluginConsent";
import { Toggle } from "./Toggle";

const REPO_HINT = "owner/repo, or owner/repo/path@branch";

function parseRepo(raw: string): Record<string, unknown> | null {
  const [location, ref] = raw.trim().replace(/^https:\/\/github\.com\//, "").split("@");
  const [owner, repo, ...rest] = location.replace(/\.git$/, "").split("/");
  if (!owner || !repo) return null;
  return { kind: "github", repo: `${owner}/${repo}`, path: rest.join("/"), ref: ref || "HEAD" };
}

function readZip(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function Runs({ platforms }: { platforms: string[] | undefined }) {
  const engine = useStore((s) => s.engine);
  const labels = engine?.plugin_platforms ?? {};
  const host = engine?.host ?? "";
  const here = runsHere(platforms, host);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {(platforms ?? []).map((platform) => (
        <span key={platform} className={`chip ${runsHere([platform], host) ? "chip-ok" : ""}`}>
          {labels[platform] ?? platform}
        </span>
      ))}
      {!here && <span className="chip chip-bad">Not on {labels[host] ?? host}</span>}
    </div>
  );
}

function Installed({ plugin, permissions, hubOnly }: { plugin: PluginRecord; permissions: Permission[]; hubOnly: boolean }) {
  const send = useStore((s) => s.send);
  const [open, setOpen] = useState(false);
  const [consenting, setConsenting] = useState(false);
  const accepted = plugin.manifest.permissions.every((p) => plugin.granted.includes(p));
  const origin =
    plugin.source.kind === "github"
      ? `${plugin.source.repo}${plugin.source.path ? `/${plugin.source.path}` : ""} @ ${String(plugin.source.ref).slice(0, 7)}`
      : (plugin.source.filename ?? "imported file");

  return (
    <div className="rounded border border-line-0 bg-ink-1 p-3 space-y-2.5">
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-0 truncate flex-1">
          {plugin.manifest.name} <span className="text-text-2">v{plugin.manifest.version}</span>
        </span>
        <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        <Toggle
          label={`Enable ${plugin.manifest.name}`}
          hideLabel
          on={plugin.enabled}
          onChange={(on) =>
            on && !accepted ? setConsenting(true) : send({ cmd: "plugin.update", id: plugin.id, patch: { enabled: on } })
          }
        />
      </div>
      <Runs platforms={plugin.manifest.platforms} />
      {plugin.failure && <span className="block text-[0.7rem] text-bad">Stopped: {plugin.failure}</span>}
      <span className="mono block truncate text-[0.65rem] text-text-2">{origin}</span>
      <div className="flex items-center gap-2">
        <button className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Permissions"}
        </button>
        {plugin.source.kind === "github" && (
          <button className="btn" onClick={() => send({ cmd: "plugin.install", source: { ...plugin.source, ref: "HEAD" } })}>
            Update
          </button>
        )}
        <button className="btn btn-danger" onClick={() => send({ cmd: "plugin.remove", id: plugin.id })}>
          Remove
        </button>
      </div>
      {!accepted && <span className="block text-[0.7rem] text-warn">Asks for permissions you have not accepted yet.</span>}
      {open && <PermissionList plugin={plugin} permissions={permissions} hubOnly={hubOnly} />}
      {consenting && (
        <ConsentDialog plugin={plugin} permissions={permissions} hubOnly={hubOnly} onClose={() => setConsenting(false)} />
      )}
    </div>
  );
}

function Available({ entry, installed }: { entry: CatalogueEntry; installed: boolean }) {
  const installPlugin = useStore((s) => s.installPlugin);
  const isPending = useStore((s) => s.isPending);
  const host = useStore((s) => s.engine?.host ?? "");
  const here = runsHere(entry.platforms, host);

  return (
    <div className="rounded border border-line-0 bg-ink-1 p-3 space-y-2.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <span className="block truncate text-xs text-text-0">
            {entry.name} {entry.version && <span className="text-text-2">v{entry.version}</span>}
          </span>
          <span className="block text-[0.7rem] leading-relaxed text-text-2">{entry.description}</span>
        </div>
        <button
          className="btn btn-primary"
          disabled={installed || !here || isPending("plugin.install")}
          onClick={() => installPlugin({ kind: "github", repo: entry.repo, path: entry.path ?? "", ref: entry.ref })}
        >
          {installed ? "Installed" : "Install"}
        </button>
      </div>
      <Runs platforms={entry.platforms} />
    </div>
  );
}

export function PluginsTab() {
  const { engine, catalogue, fetchCatalogue, installPlugin, isPending, toast } = useStore();
  const [repo, setRepo] = useState("");
  const [platform, setPlatform] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const plugins = engine?.plugins ?? [];
  const permissions = engine?.plugin_permissions ?? [];
  const labels = engine?.plugin_platforms ?? {};
  const host = engine?.host ?? "";

  useEffect(() => {
    if (catalogue === null) fetchCatalogue();
  }, []);

  const bases = Object.keys(labels).filter((id) => !id.includes("-"));
  const chosen = platform ?? bases.find((id) => runsHere([id], host)) ?? "";
  const target = chosen === "" ? "" : runsHere([chosen], host) ? host : chosen;
  const listed = (catalogue ?? []).filter((entry) => target === "" || runsHere(entry.platforms, target));

  const installFromRepo = () => {
    const source = parseRepo(repo);
    if (!source) return toast("error", `${REPO_HINT}, that did not look like either`);
    installPlugin(source);
    setRepo("");
  };

  return (
    <div className="space-y-4">
      <div>
        <span className="label block">Plugins</span>
        <span className="mt-1 block text-[0.7rem] leading-relaxed text-text-2">
          Plugins are third-party code. They install switched off, and enabling one asks you to accept everything it wants
          first. Verified ones match a reviewed entry in PrintGuard's catalogue by hash; anything else is unreviewed, so read
          it before you enable it.
        </span>
      </div>

      {plugins.length > 0 && (
        <div className="space-y-2">
          {plugins.map((plugin) => (
            <Installed key={plugin.id} plugin={plugin} permissions={permissions} hubOnly={engine?.plugin_host ?? false} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="label flex-1">Catalogue</span>
        {bases.map((id) => (
          <button
            key={id}
            className={`chip cursor-pointer hover:opacity-80 ${chosen === id ? "chip-accent" : ""}`}
            aria-pressed={chosen === id}
            onClick={() => setPlatform(id)}
          >
            {labels[id]}
          </button>
        ))}
        <button
          className={`chip cursor-pointer hover:opacity-80 ${chosen === "" ? "chip-accent" : ""}`}
          aria-pressed={chosen === ""}
          onClick={() => setPlatform("")}
        >
          Everything
        </button>
      </div>

      {catalogue === null ? (
        <span className="block text-[0.7rem] text-text-2">Loading the catalogue…</span>
      ) : listed.length === 0 ? (
        <span className="block text-[0.7rem] text-text-2">
          {catalogue.length === 0
            ? "No plugins listed, or the catalogue could not be reached."
            : `Nothing listed for ${labels[chosen] ?? chosen}.`}
        </span>
      ) : (
        <div className="space-y-2">
          {listed.map((entry) => (
            <Available key={entry.id} entry={entry} installed={plugins.some((p) => p.id === entry.id)} />
          ))}
        </div>
      )}

      <span className="label block">Install from anywhere</span>
      <div className="flex gap-2">
        <input
          className="field flex-1"
          placeholder={REPO_HINT}
          value={repo}
          onChange={(event) => setRepo(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && installFromRepo()}
        />
        <button className="btn whitespace-nowrap" disabled={!repo.trim() || isPending("plugin.install")} onClick={installFromRepo}>
          {isPending("plugin.install") ? "…" : "Install"}
        </button>
      </div>
      <div className="flex items-center gap-2">
        <button className="btn" onClick={() => file.current?.click()}>
          Import a .zip
        </button>
        <input
          ref={file}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={async (event) => {
            const chosen = event.target.files?.[0];
            event.target.value = "";
            if (chosen) installPlugin({ kind: "file", filename: chosen.name }, await readZip(chosen));
          }}
        />
        <span className="text-[0.7rem] text-text-2">A folder with plugin.json and plugin.js or worker.js, zipped.</span>
      </div>
    </div>
  );
}
