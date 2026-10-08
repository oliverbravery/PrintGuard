import { useEffect, useRef, useState, type ReactNode } from "react";
import { fromBase64, renderMarkdown } from "../markdown";
import { pluginFile, repositoryFiles, runsHere } from "../plugins";
import { useStore } from "../store";
import type { CatalogueEntry, PluginManifest, PluginRecord } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { ConsentDialog, PermissionList } from "./PluginConsent";
import { PluginSecrets } from "./PluginSecrets";
import { useSettingsFooter } from "./SettingsFooter";
import { Toggle } from "./Toggle";
import { webUrl } from "../urls";

const REPO_HINT = "owner/repo, or owner/repo/path@branch";
const MAX_ZIP_BYTES = 12 * 1024 * 1024;

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
      onClick={() => installPlugin({ kind: "github", repo: entry.repo, path: entry.path ?? "", ref: entry.ref })}
    >
      {installed ? "Installed" : "Install"}
    </button>
  );
}

function EnableToggle({ plugin }: { plugin: PluginRecord }) {
  const send = useStore((s) => s.send);
  const permissions = useStore((s) => s.engine?.plugin_permissions ?? []);
  const [consenting, setConsenting] = useState(false);
  const accepted = plugin.manifest.permissions.every((p) => plugin.granted.includes(p));
  return (
    <>
      <Toggle
        label={`Enable ${plugin.manifest.name}`}
        hideLabel
        on={plugin.enabled}
        onChange={(on) =>
          on && !accepted ? setConsenting(true) : send({ cmd: "plugin.update", id: plugin.id, patch: { enabled: on } })
        }
      />
      {consenting && (
        <ConsentDialog plugin={plugin} permissions={permissions} onClose={() => setConsenting(false)} />
      )}
    </>
  );
}

const IMAGE_TYPES: Record<string, string> = { png: "png", jpg: "jpeg", jpeg: "jpeg", webp: "webp", gif: "gif", svg: "svg+xml" };

function dataUrl(page: Record<string, string>, path: string | undefined): string | null {
  const data = path ? page[path] : undefined;
  if (!data || !path) return null;
  const kind = IMAGE_TYPES[path.split(".").pop()!.toLowerCase()] ?? "png";
  return `data:image/${kind};base64,${data}`;
}

function installedIcon(plugin: PluginRecord, page: Record<string, string> | undefined): string | null {
  return plugin.source.kind === "github"
    ? pluginFile(plugin.source, plugin.manifest.icon)
    : dataUrl(page ?? {}, plugin.manifest.icon);
}

interface StoreItem {
  id: string;
  entry?: CatalogueEntry;
  plugin?: PluginRecord;
}

function PluginCard({ item, onOpen }: { item: StoreItem; onOpen: () => void }) {
  const page = useStore((s) => s.pluginPages[item.id]);
  const fetchPluginPage = useStore((s) => s.fetchPluginPage);
  const { entry, plugin } = item;
  const name = plugin?.manifest.name ?? entry?.name ?? item.id;
  const description = plugin?.manifest.description || entry?.description || "";
  const attention = plugin && (plugin.failure || !plugin.manifest.permissions.every((p) => plugin.granted.includes(p)));
  const reconnecting = useStore((s) => s.reconnecting);

  useEffect(() => {
    if (plugin && plugin.source.kind !== "github" && plugin.manifest.icon && !reconnecting) fetchPluginPage(plugin.id);
  }, [plugin?.id, reconnecting]);

  return (
    <div className="relative flex items-center gap-3 rounded border border-line-0 bg-ink-1 p-3 text-left transition-colors hover:border-accent has-[:focus-visible]:border-accent">
      <PluginIcon url={plugin ? installedIcon(plugin, page) : pluginFile(entry!, entry!.icon)} name={name} size={44} />
      <div className="min-w-0 flex-1 space-y-0.5">
        <span className="flex items-center gap-2 text-xs text-text-0">
          <button className="min-w-0 cursor-pointer truncate text-left after:absolute after:inset-0" onClick={onOpen}>
            {name}
          </button>
          {attention && <span className="chip chip-bad">needs attention</span>}
        </span>
        <span className="clamp-2 block text-[0.7rem] leading-snug text-text-2">{description}</span>
      </div>
      <span className="relative">{plugin ? <EnableToggle plugin={plugin} /> : <InstallButton entry={entry!} installed={false} />}</span>
    </div>
  );
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
  meta,
  extra,
  children,
}: {
  icon: string | null;
  name: string;
  author: string;
  version: string;
  platforms: string[] | undefined;
  action?: ReactNode;
  media: { src: string; href?: string }[];
  readme: { text: string; base?: string; skip?: string[]; sources?: Record<string, string>; imagePrefixes: string[] } | null | undefined;
  fallback: string;
  manifest: PluginManifest;
  origin: string;
  onBack: () => void;
  meta?: ReactNode;
  extra?: ReactNode;
  children?: ReactNode;
}) {
  const permissions = useStore((s) => s.engine?.plugin_permissions ?? []);
  useSettingsFooter(origin);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <button className="btn" onClick={onBack}>
          Back to all plugins
        </button>
        {extra}
      </div>
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

      {meta}

      {media.length > 0 && (
        <div className="space-y-2">
          {media.map((shot) => (
            <a key={shot.src} href={shot.href} target="_blank" rel="noreferrer" className="block">
              <img
                src={shot.src}
                alt={`${name} screenshot`}
                loading="lazy"
                className="block w-full rounded border border-line-0"
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
              imagePrefixes: readme.imagePrefixes,
            }),
          }}
        />
      ) : (
        <p className="text-[0.78rem] leading-relaxed text-text-1">{fallback}</p>
      )}

      {children}

      <div>
        <span className="label mb-2 block">{action ? "Permissions it will ask for" : "Permissions it asks for"}</span>
        <PermissionList plugin={{ manifest }} permissions={permissions} />
      </div>
    </div>
  );
}

function InstalledDetail({ plugin, onBack }: { plugin: PluginRecord; onBack: () => void }) {
  const send = useStore((s) => s.send);
  const page = useStore((s) => s.pluginPages[plugin.id]);
  const fetchPluginPage = useStore((s) => s.fetchPluginPage);
  const installPlugin = useStore((s) => s.installPlugin);
  const [fetched, setFetched] = useState<string | null | undefined>(undefined);
  const fromRepo = plugin.source.kind === "github";
  const manifest = plugin.manifest;
  const accepted = manifest.permissions.every((p) => plugin.granted.includes(p));
  const reconnecting = useStore((s) => s.reconnecting);
  const updating = useStore((s) => s.isPending("plugin.install"));

  useEffect(() => {
    if (!fromRepo && !reconnecting) fetchPluginPage(plugin.id);
  }, [plugin.id, reconnecting]);

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
        : { text: fetched, base: pluginFile(plugin.source, "README.md") ?? undefined, skip: manifest.media ?? [], imagePrefixes: [repositoryFiles({ repo: plugin.source.repo!, ref: plugin.source.ref! })] }
    : page === undefined
      ? undefined
      : stored
        ? { text: fromBase64(stored), skip: manifest.media ?? [], sources, imagePrefixes: [] }
        : null;

  return (
    <PluginPage
      icon={installedIcon(plugin, page)}
      name={manifest.name}
      author={manifest.author}
      version={manifest.version}
      platforms={manifest.platforms}
      action={<EnableToggle plugin={plugin} />}
      media={media}
      readme={readme}
      fallback={manifest.description}
      manifest={manifest}
      origin={origin}
      onBack={onBack}
      extra={
        <ConfirmButton
          onConfirm={() => {
            send({ cmd: "plugin.remove", id: plugin.id });
            onBack();
          }}
        >
          Remove
        </ConfirmButton>
      }
      meta={
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
            {fromRepo && (
              <button className="btn" disabled={updating} onClick={() => installPlugin({ ...plugin.source, ref: plugin.source.branch ?? "HEAD" })}>
                {updating ? "Updating…" : "Update"}
              </button>
            )}
          </div>
          {plugin.failure && <span className="block text-[0.7rem] text-bad">Stopped: {plugin.failure}</span>}
          {!accepted && <span className="block text-[0.7rem] text-warn">Waiting on permissions you have not accepted.</span>}
        </div>
      }
    >
      {plugin.enabled && <PluginSecrets plugin={plugin} />}
    </PluginPage>
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

const listOfText = (value: unknown) => (Array.isArray(value) && value.every((item) => typeof item === "string") ? (value as string[]) : undefined);

const mapOfText = (value: unknown) =>
  typeof value === "object" && value !== null && !Array.isArray(value) && Object.values(value).every((item) => typeof item === "string")
    ? (value as Record<string, string>)
    : undefined;

function readableSignIn(value: unknown): PluginManifest["oauth"] | undefined {
  const block = (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
  const addresses = [block.authorize_url, block.token_url];
  if (!addresses.every((url) => typeof url === "string" && webUrl(url) !== null) || typeof block.label !== "string") return undefined;
  return { authorize_url: block.authorize_url as string, token_url: block.token_url as string, register_url: "", scopes: [], label: block.label };
}

function readableManifest(entry: CatalogueEntry, raw: Record<string, unknown>): PluginManifest {
  const bare = bareManifest(entry);
  return {
    ...bare,
    permissions: listOfText(raw.permissions) ?? bare.permissions,
    reasons: mapOfText(raw.reasons) ?? bare.reasons,
    urls: listOfText(raw.urls) ?? bare.urls,
    provides: mapOfText(raw.provides) ?? bare.provides,
    consumes: listOfText(raw.consumes) ?? bare.consumes,
    oauth: readableSignIn(raw.oauth) ?? bare.oauth,
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
        if (raw && typeof raw === "object") setManifest(readableManifest(entry, raw));
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
          : { text: readme, base: pluginFile(entry, "README.md") ?? undefined, skip: entry.media ?? [], imagePrefixes: [repositoryFiles(entry)] }
      }
      fallback={entry.description ?? ""}
      manifest={manifest}
      origin={`${entry.repo}${entry.path ? `/${entry.path}` : ""} @ ${entry.ref.slice(0, 7)}`}
      onBack={onBack}
    />
  );
}

export function PluginsTab() {
  const { engine, catalogue, reconnecting, fetchCatalogue, installPlugin, isPending, toast } = useStore();
  const [repo, setRepo] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const plugins = engine?.plugins ?? [];
  const labels = engine?.plugin_platforms ?? {};
  const host = engine?.host ?? "";

  useEffect(() => {
    if (catalogue === null && !reconnecting) fetchCatalogue();
  }, [reconnecting]);

  const items: StoreItem[] = [
    ...(catalogue ?? []).map((entry) => ({ id: entry.id, entry, plugin: plugins.find((p) => p.id === entry.id) })),
    ...plugins.filter((p) => !(catalogue ?? []).some((entry) => entry.id === p.id)).map((plugin) => ({ id: plugin.id, plugin })),
  ];

  const bases = Object.keys(labels).filter((id) => !id.includes("-"));
  const chosen = filter ?? bases.find((id) => runsHere([id], host)) ?? "";
  const target = chosen === "" || chosen === "installed" ? "" : runsHere([chosen], host) ? host : chosen;
  const needle = query.trim().toLowerCase();
  const listed = items.filter((item) => {
    const platforms = item.entry?.platforms ?? item.plugin?.manifest.platforms;
    const words = [
      item.plugin?.manifest.name ?? item.entry?.name ?? "",
      item.plugin?.manifest.description ?? item.entry?.description ?? "",
      item.plugin?.manifest.author ?? item.entry?.author ?? "",
      item.id,
    ];
    if (chosen === "installed" && !item.plugin) return false;
    if (target !== "" && !runsHere(platforms, target)) return false;
    return needle === "" || words.some((text) => text.toLowerCase().includes(needle));
  });

  const opened = items.find((item) => item.id === openId);
  if (opened?.plugin) return <InstalledDetail plugin={opened.plugin} onBack={() => setOpenId(null)} />;
  if (opened?.entry) {
    return <StoreDetail entry={opened.entry} installed={false} onBack={() => setOpenId(null)} />;
  }

  const installFromRepo = () => {
    const source = parseRepo(repo);
    if (!source) return toast("error", `${REPO_HINT}, that did not look like either`);
    if (installPlugin(source)) setRepo("");
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

      <div className="flex flex-wrap items-center gap-2">
        <span className="label flex-1">Catalogue</span>
        {plugins.length > 0 && (
          <button
            className={`chip cursor-pointer hover:opacity-80 ${chosen === "installed" ? "chip-accent" : ""}`}
            aria-pressed={chosen === "installed"}
            onClick={() => setFilter("installed")}
          >
            Installed
          </button>
        )}
        {bases.map((id) => (
          <button
            key={id}
            className={`chip cursor-pointer hover:opacity-80 ${chosen === id ? "chip-accent" : ""}`}
            aria-pressed={chosen === id}
            onClick={() => setFilter(id)}
          >
            {labels[id]}
          </button>
        ))}
        <button
          className={`chip cursor-pointer hover:opacity-80 ${chosen === "" ? "chip-accent" : ""}`}
          aria-pressed={chosen === ""}
          onClick={() => setFilter("")}
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

      {(catalogue === null || listed.length === 0) && (
        <span className="block text-[0.7rem] text-text-2">
          {catalogue === null
            ? "Loading the catalogue…"
            : items.length === 0
              ? "Nothing listed, or the catalogue is unreachable."
              : needle
                ? `Nothing matches "${query.trim()}".`
                : chosen === "installed"
                  ? "Nothing installed yet."
                  : `Nothing listed for ${labels[chosen] ?? chosen}.`}
        </span>
      )}
      {listed.length > 0 && (
        <div className="space-y-2">
          {listed.map((item) => (
            <PluginCard key={item.id} item={item} onOpen={() => setOpenId(item.id)} />
          ))}
        </div>
      )}

      <span className="label block">Install from anywhere</span>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          installFromRepo();
        }}
      >
        <input className="field flex-1" placeholder={REPO_HINT} aria-label="GitHub repository" value={repo} onChange={(event) => setRepo(event.target.value)} />
        <button type="submit" className="btn whitespace-nowrap" disabled={!repo.trim() || isPending("plugin.install")}>
          {isPending("plugin.install") ? "…" : "Install"}
        </button>
      </form>
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
            if (!chosen) return;
            if (chosen.size > MAX_ZIP_BYTES) return toast("error", `${chosen.name} is over 12 MB, the most a plugin can be`);
            installPlugin({ kind: "file", filename: chosen.name }, await readZip(chosen));
          }}
        />
        <span className="text-[0.7rem] text-text-2">A zipped folder with plugin.json and plugin.js or worker.js.</span>
      </div>
    </div>
  );
}
