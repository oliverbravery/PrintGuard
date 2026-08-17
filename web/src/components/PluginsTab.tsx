import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import type { CatalogueEntry, Permission, PluginRecord } from "../types";
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

function Permissions({
  plugin,
  permissions,
  hubOnly,
}: {
  plugin: PluginRecord;
  permissions: Permission[];
  hubOnly: boolean;
}) {
  const send = useStore((s) => s.send);
  const asked = permissions.filter((p) => plugin.manifest.permissions.includes(p.id));
  if (asked.length === 0) return <span className="text-[0.7rem] text-text-2">Asks for nothing beyond drawing its panel.</span>;
  return (
    <div className="space-y-1.5">
      {asked.map((permission) => {
        const granted = plugin.granted.includes(permission.id);
        const inert = permission.hub_only && !hubOnly;
        return (
          <label key={permission.id} className="flex items-start gap-2 text-[0.7rem]">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={granted}
              disabled={inert}
              onChange={(event) =>
                send({
                  cmd: "plugin.update",
                  id: plugin.id,
                  patch: {
                    granted: event.target.checked
                      ? [...plugin.granted, permission.id]
                      : plugin.granted.filter((p) => p !== permission.id),
                  },
                })
              }
            />
            <span>
              <span className={permission.risky ? "text-warn" : "text-text-1"}>{permission.label}</span>
              {permission.hosts && plugin.manifest.hosts.length > 0 && (
                <span className="mono text-text-2"> ({plugin.manifest.hosts.join(", ")})</span>
              )}
              <span className="block text-text-2">
                {inert ? "Only does anything on a hub." : permission.description}
              </span>
            </span>
          </label>
        );
      })}
    </div>
  );
}

function Installed({ plugin, permissions, hubOnly }: { plugin: PluginRecord; permissions: Permission[]; hubOnly: boolean }) {
  const send = useStore((s) => s.send);
  const unreviewed = plugin.granted.length === 0 && plugin.manifest.permissions.length > 0;
  const [open, setOpen] = useState(unreviewed);
  const origin =
    plugin.source.kind === "github"
      ? `${plugin.source.repo}${plugin.source.path ? `/${plugin.source.path}` : ""} @ ${String(plugin.source.ref).slice(0, 7)}`
      : (plugin.source.filename ?? "imported file");

  return (
    <div className="rounded border border-line-0 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-0 truncate flex-1">
          {plugin.manifest.name} <span className="text-text-2">v{plugin.manifest.version}</span>
        </span>
        <span className={`chip ${plugin.verified ? "chip-ok" : ""}`}>{plugin.verified ? "verified" : "third party"}</span>
        <Toggle
          label={`Enable ${plugin.manifest.name}`}
          hideLabel
          on={plugin.enabled}
          onChange={(on) => send({ cmd: "plugin.update", id: plugin.id, patch: { enabled: on } })}
        />
      </div>
      {plugin.failure && <span className="block text-[0.7rem] text-bad">Stopped: {plugin.failure}</span>}
      <span className="mono block truncate text-[0.65rem] text-text-2">{origin}</span>
      <div className="flex items-center gap-2">
        <button className="btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Permissions"}
        </button>
        {plugin.source.kind === "github" && (
          <button
            className="btn"
            onClick={() =>
              send({ cmd: "plugin.install", source: { ...plugin.source, ref: "HEAD" }, granted: plugin.granted })
            }
          >
            Update
          </button>
        )}
        <button className="btn btn-danger" onClick={() => send({ cmd: "plugin.remove", id: plugin.id })}>
          Remove
        </button>
      </div>
      {open && <Permissions plugin={plugin} permissions={permissions} hubOnly={hubOnly} />}
    </div>
  );
}

function Available({ entry, installed, permissions }: { entry: CatalogueEntry; installed: boolean; permissions: Permission[] }) {
  const installPlugin = useStore((s) => s.installPlugin);
  const isPending = useStore((s) => s.isPending);
  const [asking, setAsking] = useState(false);
  const wants = permissions.filter((p) => (entry.permissions ?? []).includes(p.id));

  const install = () =>
    installPlugin({ kind: "github", repo: entry.repo, path: entry.path ?? "", ref: entry.ref }, undefined, entry.permissions);

  return (
    <div className="rounded border border-line-0 p-3 space-y-2">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <span className="block truncate text-xs text-text-0">
            {entry.name} {entry.version && <span className="text-text-2">v{entry.version}</span>}
          </span>
          <span className="block text-[0.7rem] text-text-2">{entry.description}</span>
        </div>
        <button
          className="btn btn-primary"
          disabled={installed || isPending("plugin.install")}
          onClick={() => (wants.length === 0 ? install() : setAsking(!asking))}
        >
          {installed ? "Installed" : "Install"}
        </button>
      </div>
      {asking && !installed && (
        <div className="space-y-2 border-t border-line-0 pt-2">
          <span className="block text-[0.7rem] text-text-1">Installing lets it:</span>
          <ul className="space-y-1">
            {wants.map((permission) => (
              <li key={permission.id} className="text-[0.7rem]">
                <span className={permission.risky ? "text-warn" : "text-text-1"}>{permission.label}</span>
                <span className="block text-text-2">{permission.description}</span>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={install}>
              Install and allow
            </button>
            <button className="btn" onClick={() => setAsking(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function PluginsTab() {
  const { engine, catalogue, fetchCatalogue, installPlugin, isPending, toast } = useStore();
  const [repo, setRepo] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const plugins = engine?.plugins ?? [];
  const permissions = engine?.plugin_permissions ?? [];

  useEffect(() => {
    if (catalogue === null) fetchCatalogue();
  }, []);

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
          Plugins are third-party code. They run in a sandbox with no network and no access to your credentials, cameras or
          tokens, and only do what you grant them. Verified ones match a reviewed entry in PrintGuard's catalogue by hash;
          anything else is unreviewed, so read it before you install it.
        </span>
      </div>

      {plugins.length > 0 && (
        <div className="space-y-2">
          {plugins.map((plugin) => (
            <Installed key={plugin.id} plugin={plugin} permissions={permissions} hubOnly={engine?.plugin_host ?? false} />
          ))}
        </div>
      )}

      <span className="label block">Catalogue</span>
      {catalogue === null ? (
        <span className="block text-[0.7rem] text-text-2">Loading the catalogue…</span>
      ) : catalogue.length === 0 ? (
        <span className="block text-[0.7rem] text-text-2">No plugins listed, or the catalogue could not be reached.</span>
      ) : (
        <div className="space-y-2">
          {catalogue.map((entry) => (
            <Available
              key={entry.id}
              entry={entry}
              installed={plugins.some((p) => p.id === entry.id)}
              permissions={permissions}
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
        <span className="text-[0.7rem] text-text-2">A folder with plugin.json and plugin.js or worker.js, zipped.</span>
      </div>
    </div>
  );
}
