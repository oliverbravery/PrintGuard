import { useEffect, useState } from "react";
import { useStore } from "../store";
import type { AdapterMeta, Printer } from "../types";
import { Dialog } from "./Dialog";
import { DeviceChip } from "./MonitorTile";
import { SchemaForm } from "./SchemaForm";

function providerLabel(integrations: AdapterMeta[], id: string): string {
  return integrations.find((i) => i.id === id)?.label ?? id;
}

function mixedContent(mode: string | null | undefined, config: Record<string, string>): boolean {
  return mode === "local" && location.protocol === "https:" && Object.values(config).some((v) => v.startsWith("http://"));
}

function MixedContentNote() {
  return (
    <p className="text-xs leading-snug text-warn break-words">
      PrintGuard is served over HTTPS, so the browser blocks this http:// address as mixed content in local mode. Switch to hub
      mode, or use an https:// printer URL.
    </p>
  );
}

function TestRow({ provider, config }: { provider: string; config: Record<string, string> }) {
  const { printerTest, testing, testPrinter } = useStore();
  return (
    <div className="flex items-center gap-3">
      <button className="btn" disabled={!provider || testing} onClick={() => testPrinter(provider, config)}>
        {testing ? "Testing…" : "Test connection"}
      </button>
      {printerTest?.ok && <span className="chip chip-ok">ok — {printerTest.status}</span>}
      {printerTest && !printerTest.ok && <span className="chip chip-bad">{printerTest.error || printerTest.status || "failed"}</span>}
    </div>
  );
}

function PrinterRow({ printer }: { printer: Printer }) {
  const { engine, send, isPending, mode } = useStore();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(printer.name);
  const [config, setConfig] = useState<Record<string, string>>(printer.config ?? {});
  const integrations = engine?.integrations ?? [];
  const meta = integrations.find((i) => i.id === printer.provider);

  useEffect(() => {
    setName(printer.name);
    setConfig(printer.config ?? {});
  }, [printer.id]);

  const dirty = name !== printer.name || JSON.stringify(config) !== JSON.stringify(printer.config ?? {});

  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2">
        <span className={`led ${printer.online ? "led-on" : "led-off"}`} />
        <div className="flex-1 min-w-0 leading-tight">
          <div className="text-sm font-medium truncate">{printer.name}</div>
          <div className="mono text-[0.62rem] text-text-2 truncate">{providerLabel(integrations, printer.provider)}</div>
        </div>
        <DeviceChip state={printer.device_state ?? undefined} />
        <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide" : "Edit"}
        </button>
        <button
          className="btn btn-danger !py-1 !px-2.5 !text-[0.62rem]"
          disabled={isPending("printer.remove")}
          onClick={() => send({ cmd: "printer.remove", id: printer.id })}
        >
          {isPending("printer.remove") ? "Removing…" : "Remove"}
        </button>
      </div>
      {open && meta && (
        <div className="px-3 pb-3 pt-1 border-t border-line-0 space-y-3">
          <input className="field" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <SchemaForm meta={meta} value={config} onChange={setConfig} />
          {mixedContent(mode, config) && <MixedContentNote />}
          <TestRow provider={printer.provider} config={config} />
          <button
            className="btn btn-primary w-full !py-1.5"
            disabled={!dirty || isPending("printer.update")}
            onClick={() => send({ cmd: "printer.update", id: printer.id, patch: { name: name.trim(), config } })}
          >
            {isPending("printer.update") ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}

function RegisterPrinter() {
  const { engine, send, isPending, mode } = useStore();
  const integrations = (engine?.integrations ?? []).filter((i) => mode === "hub" || i.browser_ok);
  const [provider, setProvider] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const meta = integrations.find((i) => i.id === provider);
  const busy = isPending("printer.add");

  return (
    <div className="space-y-3">
      <select
        className="field"
        value={provider}
        onChange={(e) => {
          setProvider(e.target.value);
          setConfig({});
        }}
      >
        <option value="">Select a printer service…</option>
        {integrations.map((i) => (
          <option key={i.id} value={i.id}>
            {i.label}
          </option>
        ))}
      </select>
      {meta && (
        <>
          <input className="field" placeholder={`Name (e.g. ${meta.label} — Ender 3)`} value={name} onChange={(e) => setName(e.target.value)} />
          <SchemaForm meta={meta} value={config} onChange={setConfig} />
          {mixedContent(mode, config) && <MixedContentNote />}
          <TestRow provider={provider} config={config} />
          <button
            className="btn btn-primary w-full"
            disabled={busy}
            onClick={() => {
              send({ cmd: "printer.add", printer: { name: name.trim(), provider, config } });
              setProvider("");
              setName("");
              setConfig({});
            }}
          >
            {busy ? "Registering…" : "Register printer"}
          </button>
        </>
      )}
    </div>
  );
}

export function PrintersDialog() {
  const { engine, openDialog } = useStore();
  const close = () => openDialog(null);
  const printers = engine?.printers ?? [];
  return (
    <Dialog title="Printer registry" onClose={close}>
      {printers.length > 0 && (
        <div className="space-y-2 mb-6">
          {printers.map((printer) => (
            <PrinterRow key={printer.id} printer={printer} />
          ))}
        </div>
      )}
      <div className="label mb-3">Register new</div>
      <RegisterPrinter />
    </Dialog>
  );
}
