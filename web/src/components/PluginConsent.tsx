import { useEffect } from "react";
import type { Finding } from "../lint";
import { useStore } from "../store";
import type { Permission, PluginManifest, PluginRecord } from "../types";
import { phrase, reachesLocal } from "../urls";
import { Dialog } from "./Dialog";

export function PermissionList({ plugin, permissions, hubOnly }: { plugin: { manifest: PluginManifest }; permissions: Permission[]; hubOnly: boolean }) {
  const asked = permissions.filter((p) => plugin.manifest.permissions.includes(p.id));
  if (asked.length === 0) return <span className="text-[0.7rem] text-text-2">Asks for nothing.</span>;
  return (
    <ul className="space-y-2">
      {asked.map((permission) => (
        <li key={permission.id} className="text-[0.7rem]">
          <span className={permission.risky ? "text-warn" : "text-text-1"}>{permission.label}</span>
          <span className="block text-text-2">{permission.description}</span>
          {permission.urls && (
            <ul className="text-text-2">
              {plugin.manifest.urls
                .filter((url) => reachesLocal(url) === (permission.id === "net:local"))
                .map((url) => (
                  <li key={url}>{phrase(url)}</li>
                ))}
            </ul>
          )}
          {permission.id === "oauth" && <span className="block text-text-2">{plugin.manifest.oauth.label}</span>}
          {permission.id === "link:provide" && (
            <ul className="text-text-2">
              {Object.entries(plugin.manifest.provides).map(([channel, what]) => (
                <li key={channel}>
                  {channel}, {what}
                </li>
              ))}
            </ul>
          )}
          {permission.channels && (
            <ul className="text-text-2">
              {plugin.manifest.consumes.map((link) => (
                <li key={link}>{link.replace(":", ", the ")} channel</li>
              ))}
            </ul>
          )}
          <span className="block text-text-1">{plugin.manifest.reasons[permission.id]}</span>
          {permission.hub_only && !hubOnly && <span className="block text-text-2">Hub only.</span>}
        </li>
      ))}
    </ul>
  );
}

function phraseFinding(finding: Finding): string {
  if (finding.kind === "unused") return `Asks for ${finding.what} but never uses it.`;
  if (finding.kind === "undeclared") return `Uses ${finding.what} without asking. PrintGuard will refuse it.`;
  return `Uses ${finding.what}, so its reach cannot be read from the code.`;
}

function Findings({ plugin }: { plugin: PluginRecord }) {
  const findings = useStore((s) => s.pluginFindings[plugin.id]);
  const checkPlugin = useStore((s) => s.checkPlugin);

  useEffect(() => {
    checkPlugin(plugin.id);
  }, [plugin.id]);

  if (findings === undefined) return <span className="block text-[0.7rem] text-text-2">Reading its code…</span>;
  if (findings.length === 0) {
    return <span className="block text-[0.7rem] text-ok">Its code matches what it asks for.</span>;
  }
  return (
    <ul className="space-y-1">
      {findings.map((finding) => (
        <li key={`${finding.kind}:${finding.what}`} className={`text-[0.7rem] ${finding.kind === "dynamic" ? "text-text-2" : "text-warn"}`}>
          {phraseFinding(finding)}
        </li>
      ))}
    </ul>
  );
}

export function ConsentDialog({ plugin, permissions, hubOnly, onClose }: { plugin: PluginRecord; permissions: Permission[]; hubOnly: boolean; onClose: () => void }) {
  const send = useStore((s) => s.send);
  const accept = () => {
    send({ cmd: "plugin.update", id: plugin.id, patch: { granted: plugin.manifest.permissions, enabled: true } });
    onClose();
  };

  return (
    <Dialog title={`Enable ${plugin.manifest.name}`} onClose={onClose}>
      <div className="space-y-3">
        <span className="block text-[0.7rem] leading-relaxed text-text-2">
          {plugin.verified
            ? "These bytes match PrintGuard's catalogue."
            : "Unreviewed third-party code. Read it first."}
        </span>
        <Findings plugin={plugin} />
        <PermissionList plugin={plugin} permissions={permissions} hubOnly={hubOnly} />
        {Object.keys(plugin.manifest.secrets).length > 0 && (
          <span className="block text-[0.7rem] text-text-2">
            It also needs {Object.keys(plugin.manifest.secrets).join(", ").replace(/[_-]/g, " ")}, which PrintGuard fills
            in for it.
          </span>
        )}
        <span className="block text-[0.7rem] text-text-2">All of it or none. Disable to stop it.</span>
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={accept}>
            Allow and enable
          </button>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </Dialog>
  );
}
