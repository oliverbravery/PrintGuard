import { useEffect, useRef, useState, type ReactNode } from "react";
import { fromBase64, renderMarkdown } from "../markdown";
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
      className="shrink-0 rounded-xl border border-line-0 bg-ink-2"
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

function Installed({
  plugin,
  permissions,
  hubOnly,
  onOpen,
}: {
  plugin: PluginRecord;
  permissions: Permission[];
  hubOnly: boolean;
  onOpen: () => void;
}) {
  const send = useStore((s) => s.send);
  const page = useStore((s) => s.pluginPages[plugin.id]);
  const fetchPluginPage = useStore((s) => s.fetchPluginPage);
  const [open, setOpen] = useState(false);
  const [consenting, setConsenting] = useState(false);
  const accepted = plugin.manifest.permissions.every((p) => plugin.granted.includes(p));
  const fromRepo = plugin.source.kind === "github";
  const origin = fromRepo
    ? `${plugin.source.repo}${plugin.source.path ? `/${plugin.source.path}` : ""} @ ${String(plugin.source.ref).slice(0, 7)}`
    : (plugin.source.filename ?? "imported file");

  useEffect(() => {
    if (!fromRepo && plugin.manifest.icon) fetchPluginPage(plugin.id);
  }, [plugin.id]);

  return (
    <div className="rounded border border-line-0 bg-ink-1 p-3 space-y-2.5">
      <div className="flex items-center gap-3">
        <button
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left"
          aria-label={`Open ${plugin.manifest.name}'s page`}
          onClick={onOpen}
        >
          <PluginIcon
            url={fromRepo ? pluginFile(plugin.source, plugin.manifest.icon) : dataUrl(page ?? {}, plugin.manifest.icon)}
            name={plugin.manifest.name}
            size={36}
          />
          <span className="text-xs text-text-0 truncate flex-1">
            {plugin.manifest.name} <span className="text-text-2">v{plugin.manifest.version}</span>
          </span>
        </button>
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

const IMAGE_TYPES: Record<string, string> = { png: "png", jpg: "jpeg", jpeg: "jpeg", webp: "webp", gif: "gif", svg: "svg+xml" };

function dataUrl(page: Record<string, string>, path: string | undefined): string | null {
  const data = path ? page[path] : undefined;
  if (!data || !path) return null;
  const kind = IMAGE_TYPES[path.split(".").pop()!.toLowerCase()] ?? "png";
  return `data:image/${kind};base64,${data}`;
}

function PluginPage({
  icon,
  name,
  author,
  version,
  platforms,
  action,
  media,
  readme,
  fallback,
  manifest,
  origin,
  onBack,
}: {
  icon: string | null;
  name: string;
  author: string;
  version: string;
  platforms: string[] | undefined;
  action?: ReactNode;
  media: { src: string; href?: string }[];
  readme: { text: string; base?: string; skip?: string[]; sources?: Record<string, string> } | null | undefined;
  fallback: string;
  manifest: PluginManifest;
  origin: string;
  onBack: () => void;
}) {
  const permissions = useStore((s) => s.engine?.plugin_permissions ?? []);
  const hubOnly = useStore((s) => s.engine?.plugin_host ?? false);
  return (
    <div className="space-y-4">
      <button className="btn" onClick={onBack}>
        ← All plugins
      </button>
      <div className="flex items-start gap-4">
        <PluginIcon url={icon} name={name} size={64} />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="display text-base font-bold leading-tight">{name}</h3>
          <span className="block text-[0.7rem] text-text-2">
            {author}
            {version && ` · v${version}`}
          </span>
          <Runs platforms={platforms} />
        </div>
        {action}
      </div>

      {media.length > 0 && (
        <div className="flex snap-x gap-2 overflow-x-auto pb-1">
          {media.map((shot) => (
            <a key={shot.src} href={shot.href} target="_blank" rel="noreferrer" className="shrink-0 snap-start">
              <img
                src={shot.src}
                alt={`${name} screenshot`}
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
            __html: renderMarkdown(readme.text, {
              base: readme.base,
              dropTitle: true,
              skip: readme.skip ?? [],
              sources: readme.sources ?? {},
            }),
          }}
        />
      ) : (
        <p className="text-[0.78rem] leading-relaxed text-text-1">{fallback}</p>
      )}

      <div>
        <span className="label mb-2 block">{action ? "Permissions it will ask for" : "Permissions it asks for"}</span>
        <PermissionList plugin={{ manifest }} permissions={permissions} hubOnly={hubOnly} />
      </div>

      <span className="mono block truncate text-[0.65rem] text-text-2">{origin}</span>
    </div>
  );
}

function InstalledDetail({ plugin, onBack }: { plugin: PluginRecord; onBack: () => void }) {
  const page = useStore((s) => s.pluginPages[plugin.id]);
  const fetchPluginPage = useStore((s) => s.fetchPluginPage);
  const [fetched, setFetched] = useState<string | null | undefined>(undefined);
  const fromRepo = plugin.source.kind === "github";
  const manifest = plugin.manifest;

  useEffect(() => {
    if (!fromRepo) fetchPluginPage(plugin.id);
  }, [plugin.id]);

  useEffect(() => {
    if (!fromRepo) return;
    const stop = new AbortController();
    const url = pluginFile(plugin.source, "README.md");
    if (!url) return setFetched(null);
    fetch(url, { signal: stop.signal })
      .then(async (answer) => setFetched(answer.ok ? await answer.text() : null))
      .catch(() => setFetched(null));
    return () => stop.abort();
  }, [plugin.id]);

  const origin = fromRepo
    ? `${plugin.source.repo}${plugin.source.path ? `/${plugin.source.path}` : ""} @ ${String(plugin.source.ref).slice(0, 7)}`
    : (plugin.source.filename ?? "imported file");
  const sources: Record<string, string> = {};
  for (const path of manifest.media ?? []) {
    const src = fromRepo ? pluginFile(plugin.source, path) : dataUrl(page ?? {}, path);
    if (src) sources[path] = src;
  }
  const media = (manifest.media ?? [])
    .filter((path) => sources[path])
    .map((path) => ({ src: sources[path], href: fromRepo ? sources[path] : undefined }));
  const stored = page?.["README.md"];
  const readme = fromRepo
    ? fetched === undefined
      ? undefined
      : fetched === null
        ? null
        : { text: fetched, base: pluginFile(plugin.source, "README.md") ?? undefined, skip: manifest.media ?? [] }
    : page === undefined
      ? undefined
      : stored
        ? { text: fromBase64(stored), skip: manifest.media ?? [], sources }
        : null;

  return (
    <PluginPage
      icon={fromRepo ? pluginFile(plugin.source, manifest.icon) : dataUrl(page ?? {}, manifest.icon)}
      name={manifest.name}
      author={manifest.author}
      version={manifest.version}
      platforms={manifest.platforms}
      media={media}
      readme={readme}
      fallback={manifest.description}
      manifest={manifest}
      origin={origin}
      onBack={onBack}
    />
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
  const [readme, setReadme] = useState<string | null | undefined>(undefined);
  const [manifest, setManifest] = useState<PluginManifest>(bareManifest(entry));

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
    <PluginPage
      icon={pluginFile(entry, entry.icon)}
      name={entry.name}
      author={entry.author ?? ""}
      version={entry.version ?? ""}
      platforms={entry.platforms}
      action={<InstallButton entry={entry} installed={installed} />}
      media={(entry.media ?? []).flatMap((shot) => {
        const src = pluginFile(entry, shot);
        return src ? [{ src, href: src }] : [];
      })}
      readme={
        readme == null
          ? readme
          : { text: readme, base: pluginFile(entry, "README.md") ?? undefined, skip: entry.media ?? [] }
      }
      fallback={entry.description ?? ""}
      manifest={manifest}
      origin={`${entry.repo}${entry.path ? `/${entry.path}` : ""} @ ${entry.ref.slice(0, 7)}`}
      onBack={onBack}
    />
  );
}

export function PluginsTab() {
  const { engine, catalogue, fetchCatalogue, installPlugin, isPending, toast } = useStore();
  const [repo, setRepo] = useState("");
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<string | null>(null);
  const [view, setView] = useState<{ kind: "entry" | "installed"; id: string } | null>(null);
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
  const needle = query.trim().toLowerCase();
  const listed = (catalogue ?? []).filter(
    (entry) =>
      (target === "" || runsHere(entry.platforms, target)) &&
      (needle === "" ||
        [entry.name, entry.description ?? "", entry.author ?? "", entry.id].some((text) => text.toLowerCase().includes(needle))),
  );
  if (view?.kind === "installed") {
    const opened = plugins.find((p) => p.id === view.id);
    if (opened) return <InstalledDetail plugin={opened} onBack={() => setView(null)} />;
  }
  if (view?.kind === "entry") {
    const opened = (catalogue ?? []).find((entry) => entry.id === view.id);
    if (opened) {
      return <StoreDetail entry={opened} installed={plugins.some((p) => p.id === opened.id)} onBack={() => setView(null)} />;
    }
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
            <Installed
              key={plugin.id}
              plugin={plugin}
              permissions={permissions}
              hubOnly={engine?.plugin_host ?? false}
              onOpen={() => setView({ kind: "installed", id: plugin.id })}
            />
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

      <input
        className="field"
        type="search"
        placeholder="Search the catalogue"
        aria-label="Search the catalogue"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {catalogue === null ? (
        <span className="block text-[0.7rem] text-text-2">Loading the catalogue…</span>
      ) : listed.length === 0 ? (
        <span className="block text-[0.7rem] text-text-2">
          {catalogue.length === 0
            ? "Nothing listed, or the catalogue is unreachable."
            : needle
              ? `Nothing matches "${query.trim()}".`
              : `Nothing listed for ${labels[chosen] ?? chosen}.`}
        </span>
      ) : (
        <div className="space-y-2">
          {listed.map((entry) => (
            <StoreCard
              key={entry.id}
              entry={entry}
              installed={plugins.some((p) => p.id === entry.id)}
              onOpen={() => setView({ kind: "entry", id: entry.id })}
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
