import { Link } from "react-router";
import { useStore } from "../store";
import type { Monitor } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { NameField } from "./NameField";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-b border-line-0 px-4 py-3">
      <h3 className="label">{title}</h3>
      {children}
    </section>
  );
}

export function MonitorSettings({ monitor }: { monitor: Monitor }) {
  const { engine, send, isPending, updateMonitor } = useStore();
  const settingsPanels = usePluginSurface("settings", monitor.id);
  const removing = isPending("monitor.remove", monitor.id);
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  return (
    <>
      <Section title="Monitor">
        <NameField name={monitor.name} onRename={(name) => updateMonitor(monitor.id, { name })} />
        <Toggle label="Watch this monitor" on={monitor.enabled} onChange={(v) => updateMonitor(monitor.id, { enabled: v })} />
        {monitor.enabled && monitor.watching === false && (
          <p className="text-sm text-text-2">
            {camera
              ? `On standby while the printer is ${printer?.device_state?.status ?? "not printing"}. Watching resumes automatically once a print starts.`
              : "No camera linked, so nothing is being watched."}
          </p>
        )}
        {monitor.enabled && monitor.watching !== false && printer && !printer.online && (
          <p className="text-sm text-text-2">
            Still watching. The printer reports {printer.device_state?.status ?? "nothing yet"}, so PrintGuard keeps checking frames until it confirms it isn't printing.
          </p>
        )}
        <Toggle label="Push notifications" on={monitor.notify} onChange={(v) => updateMonitor(monitor.id, { notify: v })} />
      </Section>
      <Section title="Camera">
        <select className="field" aria-label="Camera" value={monitor.camera_id} onChange={(e) => updateMonitor(monitor.id, { camera_id: e.target.value })}>
          <option value="">No camera</option>
          {(engine?.cameras ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <Link to={monitor.camera_id ? `/cameras/${monitor.camera_id}` : "/cameras"} className="btn-inline">
          Manage cameras
        </Link>
      </Section>
      <Section title="Printer">
        <select className="field" aria-label="Printer" value={monitor.printer_id} onChange={(e) => updateMonitor(monitor.id, { printer_id: e.target.value })}>
          <option value="">No printer (alerts only)</option>
          {(engine?.printers ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <Link to={monitor.printer_id ? `/printers/${monitor.printer_id}` : "/printers"} className="btn-inline">
          Manage printers
        </Link>
      </Section>
      {settingsPanels.map(({ plugin, node }) => (
        <Section key={plugin.id} title={plugin.manifest.name}>
          <PluginNodeView plugin={plugin} node={node} />
        </Section>
      ))}
      <Section title="Delete">
        <p className="text-sm text-text-1">Deleting a monitor leaves its camera and printer untouched.</p>
        <ConfirmButton disabled={removing} onConfirm={() => send({ cmd: "monitor.remove", id: monitor.id })}>
          {removing ? "Deleting…" : "Delete monitor"}
        </ConfirmButton>
      </Section>
      <div className="px-4 py-2">
        <SaveStatus scope={`monitor:${monitor.id}`} />
      </div>
    </>
  );
}
