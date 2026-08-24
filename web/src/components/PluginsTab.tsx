import { useEffect, useRef, useState } from "react";
import { renderMarkdown } from "../markdown";
import { pluginFile, runsHere } from "../plugins";
import { useStore } from "../store";
import type { CatalogueEntry, Permission, PluginManifest, PluginRecord } from "../types";
import { ConsentDialog, PermissionList } from "./PluginConsent";
import { PluginSecrets } from "./PluginSecrets";
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

export function PluginIcon({ url, name, size }: { url: string | null; name: string; size: number }) {
  const [broken, setBroken] = useState(false);
  if (!url || broken) {
    return (
      <span
        aria-hidden
        className="grid shrink-0 place-items-center rounded-xl border border-line-1 bg-ink-2 text-accent display font-bold"
        style={{ width: size, height: size, fontSize: size * 0.44 }}
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={url}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      className="shrink-0 rounded-xl border border-line-0"
      style={{ width: size, height: size }}
      onError={() => setBroken(true)}
    />
  );
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

function InstallButton({ entry, installed }: { entry: CatalogueEntry; installed: boolean }) {
  const installPlugin = useStore((s) => s.installPlugin);
  const isPending = useStore((s) => s.isPending);
  const host = useStore((s) => s.engine?.host ?? "");
  const here = runsHere(entry.platforms, host);
  return (
    <button
      className="btn btn-primary shrink-0"
      disabled={installed || !here || isPending("plugin.install")}
      onClick={(event) => {
        event.stopPropagation();
        installPlugin({ kind: "github", repo: entry.repo, path: entry.path ?? "", ref: entry.ref });
      }}
    >
      {installed ? "Installed" : "Install"}
    </button>
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
      <div className="flex items-center gap-3">
        <PluginIcon url={pluginFile(plugin.source, plugin.manifest.icon)} name={plugin.manifest.name} size={36} />
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
      {!accepted && <span className="block text-[0.7rem] text-warn">Waiting on permissions you have not accepted.</span>}
      {open && <PermissionList plugin={plugin} permissions={permissions} hubOnly={hubOnly} />}
      {plugin.enabled && <PluginSecrets plugin={plugin} />}
      {consenting && (
        <ConsentDialog plugin={plugin} permissions={permissions} hubOnly={hubOnly} onClose={() => setConsenting(false)} />
      )}
    </div>
  );
}

function StoreCard({ entry, installed, onOpen }: { entry: CatalogueEntry; installed: boolean; onOpen: () => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      className="flex cursor-pointer items-center gap-3 rounded border border-line-0 bg-ink-1 p-3 text-left transition-colors hover:border-accent"
      onClick={onOpen}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), onOpen())}
    >
      <PluginIcon url={pluginFile(entry, entry.icon)} name={entry.name} size={44} />
      <div className="min-w-0 flex-1 space-y-0.5">
        <span className="block truncate text-xs text-text-0">
          {entry.name} {entry.version && <span className="text-text-2">v{entry.version}</span>}
        </span>
        <span className="clamp-2 block text-[0.7rem] leading-snug text-text-2">{entry.description}</span>
      </div>
      <InstallButton entry={entry} installed={installed} />
    </div>
  );
}

function bareManifest(entry: CatalogueEntry): PluginManifest {
  return {
    id: entry.id,
    name: entry.name,
    version: entry.version ?? "",
    description: entry.description ?? "",
    author: entry.author ?? "",
    homepage: "",
    icon: entry.icon,
    media: entry.media,
    permissions: entry.permissions ?? [],
    reasons: {},
    surfaces: (entry.surfaces ?? []) as PluginManifest["surfaces"],
    platforms: entry.platforms ?? [],
    urls: [],
    secrets: {},
    provides: {},
    consumes: [],
    oauth: {},
    events: [],
    tick_s: 0,
  };
}

function StoreDetail({ entry, installed, onBack }: { entry: CatalogueEntry; installed: boolean; onBack: () => void }) {
  const permissions = useStore((s) => s.engine?.plugin_permissions ?? []);
  const hubOnly = useStore((s) => s.engine?.plugin_host ?? false);
  const [readme, setReadme] = useState<string | null | undefined>(undefined);
  const [manifest, setManifest] = useState<PluginManifest>(bareManifest(entry));
  const base = pluginFile(entry, "README.md");

  useEffect(() => {
    const stop = new AbortController();
    const grab = async (file: string) => {
      const url = pluginFile(entry, file);
      if (!url) return null;
      const answer = await fetch(url, { signal: stop.signal });
      return answer.ok ? answer : null;
    };
    grab("README.md")
      .then(async (answer) => setReadme(answer ? await answer.text() : null))
      .catch(() => setReadme(null));
    grab("plugin.json")
      .then(async (answer) => {
        const raw = answer ? await answer.json() : null;
        if (raw) setManifest({ ...bareManifest(entry), ...raw });
      })
      .catch(() => {});
    return () => stop.abort();
  }, [entry.id]);

  return (
    <div className="space-y-4">
      <button className="btn" onClick={onBack}>
        ← All plugins
      </button>
      <div className="flex items-start gap-4">
        <PluginIcon url={pluginFile(entry, entry.icon)} name={entry.name} size={64} />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="display text-base font-bold leading-tight">{entry.name}</h3>
          <span className="block text-[0.7rem] text-text-2">
            {entry.author}
            {entry.version && ` · v${entry.version}`}
          </span>
          <Runs platforms={entry.platforms} />
        </div>
        <InstallButton entry={entry} installed={installed} />
      </div>

      {(entry.media ?? []).length > 0 && (
        <div className="flex snap-x gap-2 overflow-x-auto pb-1">
          {(entry.media ?? []).map((shot) => (
            <a key={shot} href={pluginFile(entry, shot) ?? undefined} target="_blank" rel="noreferrer" className="shrink-0 snap-start">
              <img
                src={pluginFile(entry, shot) ?? undefined}
                alt={`${entry.name} screenshot`}
                loading="lazy"
                className="h-44 w-auto max-w-none rounded border border-line-0"
              />
            </a>
          ))}
        </div>
      )}

      {readme === undefined ? (
        <span className="block text-[0.7rem] text-text-2">Reading its page…</span>
      ) : readme ? (
        <div
          className="changelog text-[0.78rem]"
          dangerouslySetInnerHTML={{
            __html: renderMarkdown(readme, { base: base ?? undefined, dropTitle: true, skip: entry.media ?? [] }),
          }}
        />
      ) : (
        <p className="text-[0.78rem] leading-relaxed text-text-1">{entry.description}</p>
      )}

      <div>
        <span className="label mb-2 block">Permissions it will ask for</span>
        <PermissionList plugin={{ manifest }} permissions={permissions} hubOnly={hubOnly} />
      </div>

      <span className="mono block truncate text-[0.65rem] text-text-2">
        {entry.repo}
        {entry.path ? `/${entry.path}` : ""} @ {entry.ref.slice(0, 7)}
      </span>
    </div>
  );
}

export function PluginsTab() {
  const { engine, catalogue, fetchCatalogue, installPlugin, isPending, toast } = useStore();
  const [repo, setRepo] = useState("");
  const [platform, setPlatform] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
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
  const detail = detailId === null ? null : (catalogue ?? []).find((entry) => entry.id === detailId);

  if (detail) {
    return (
      <StoreDetail entry={detail} installed={plugins.some((p) => p.id === detail.id)} onBack={() => setDetailId(null)} />
    );
  }

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
          Third-party code, installed switched off. Verified ones match the catalogue by hash. Read the rest before you
          enable them.
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
            ? "Nothing listed, or the catalogue is unreachable."
            : `Nothing listed for ${labels[chosen] ?? chosen}.`}
        </span>
      ) : (
        <div className="space-y-2">
          {listed.map((entry) => (
            <StoreCard
              key={entry.id}
              entry={entry}
              installed={plugins.some((p) => p.id === entry.id)}
              onOpen={() => setDetailId(entry.id)}
            />
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
        <span className="text-[0.7rem] text-text-2">A zipped folder with plugin.json and plugin.js or worker.js.</span>
      </div>
    </div>
  );
}
