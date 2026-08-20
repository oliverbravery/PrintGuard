import { useStore } from "../store";
import type { Permission, PluginRecord } from "../types";
import { Dialog } from "./Dialog";

export function PermissionList({ plugin, permissions, hubOnly }: { plugin: PluginRecord; permissions: Permission[]; hubOnly: boolean }) {
  const asked = permissions.filter((p) => plugin.manifest.permissions.includes(p.id));
  if (asked.length === 0) return <span className="text-[0.7rem] text-text-2">Asks for nothing beyond drawing its panel.</span>;
  return (
    <ul className="space-y-2">
      {asked.map((permission) => (
        <li key={permission.id} className="text-[0.7rem]">
          <span className={permission.risky ? "text-warn" : "text-text-1"}>{permission.label}</span>
          {permission.hosts && plugin.manifest.hosts.length > 0 && (
            <span className="mono text-text-2"> ({plugin.manifest.hosts.join(", ")})</span>
          )}
          <span className="block text-text-2">{permission.description}</span>
          <span className="block text-text-1">{plugin.manifest.reasons[permission.id]}</span>
          {permission.hub_only && !hubOnly && <span className="block text-text-2">Only does anything on a hub.</span>}
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
            ? "These bytes match a reviewed entry in PrintGuard's catalogue. It still only does what you allow here."
            : "This plugin is unreviewed third-party code. Read it before you allow any of this."}
        </span>
        <PermissionList plugin={plugin} permissions={permissions} hubOnly={hubOnly} />
        <span className="block text-[0.7rem] text-text-2">Enabling allows all of it. Disable the plugin to stop it.</span>
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
