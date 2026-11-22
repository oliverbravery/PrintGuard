import { Link, Navigate, useNavigate, useParams } from "react-router";
import { useStore } from "../store";
import { ConfirmButton } from "./ConfirmButton";
import { NameField } from "./NameField";
import { Page } from "./Page";
import { PluginNodeView, usePluginSurface } from "./PluginNode";
import { SaveStatus } from "./SaveStatus";
import { Toggle } from "./Toggle";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-3 border-b border-line-0 px-4 py-4 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-6">
      <h2 className="label pt-1">{title}</h2>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  );
}

export function MonitorEditPage() {
  const { monitorId } = useParams();
  const navigate = useNavigate();
  const { engine, send, isPending, updateMonitor } = useStore();
  const monitor = engine?.monitors.find((m) => m.id === monitorId);
  const settingsPanels = usePluginSurface("settings", monitorId ?? "");
  if (!monitor) return <Navigate to="/" replace />;
  const removing = isPending("monitor.remove");
  const camera = engine?.cameras.find((c) => c.id === monitor.camera_id);
  const printer = engine?.printers.find((p) => p.id === monitor.printer_id);
  return (
    <Page title={`${monitor.name} settings`} back={{ to: `/monitors/${monitor.id}`, label: "Monitors" }} subview actions={<SaveStatus scope={`monitor:${monitor.id}`} />}>
      <div className="mx-auto max-w-5xl">
        <Section title="Monitor">
          <NameField name={monitor.name} onRename={(name) => updateMonitor(monitor.id, { name })} />
          <Toggle label="Watch this monitor" on={monitor.enabled} onChange={(v) => updateMonitor(monitor.id, { enabled: v })} />
          {monitor.enabled && monitor.watching === false && (
            <p className="text-sm text-text-2">
              {camera
                ? `Standby, the printer is ${printer?.device_state?.status ?? "not printing"}. Inference resumes when it prints.`
                : "No camera, so nothing is being watched."}
            </p>
          )}
          {monitor.enabled && monitor.watching !== false && printer && !printer.online && (
            <p className="text-sm text-text-2">
              Watching. The printer reports {printer.device_state?.status ?? "nothing yet"}, so inference runs until it says it isn't printing.
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
          <p className="text-sm text-text-1">Deleting a monitor keeps its camera and printer.</p>
          <ConfirmButton
            disabled={removing}
            onConfirm={() => {
              send({ cmd: "monitor.remove", id: monitor.id });
              navigate("/", { replace: true });
            }}
          >
            {removing ? "Deleting…" : "Delete monitor"}
          </ConfirmButton>
        </Section>
      </div>
    </Page>
  );
}
