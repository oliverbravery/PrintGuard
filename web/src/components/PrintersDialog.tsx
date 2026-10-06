import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { useSubmit } from "../submit";
import type { AdapterConfig, AdapterMeta, Printer } from "../types";
import { Dialog } from "./Dialog";
import { DeviceChip } from "./MonitorTile";
import { SchemaForm, withoutSecrets } from "./SchemaForm";
import { TestRow } from "./TestRow";

const NEW_PRINTER = "new";

function providerLabel(integrations: AdapterMeta[], id: string): string {
  return integrations.find((i) => i.id === id)?.label ?? id;
}

function PrinterTest({ id, provider, config }: { id: string; provider: string; config: AdapterConfig }) {
  const { printerTest, testing, testPrinter } = useStore();
  const target = JSON.stringify([id, provider, config]);
  return (
    <TestRow
      label="Test connection"
      busyLabel="Testing…"
      busy={testing === target}
      disabled={!provider || testing !== null}
      onTest={() => testPrinter(target, provider, config, id === NEW_PRINTER ? undefined : id)}
      result={
        printerTest?.target === target
          ? {
              ok: printerTest.ok,
              message: printerTest.ok ? `ok, ${printerTest.status}` : printerTest.error || printerTest.status || "failed",
            }
          : null
      }
    />
  );
}

function PrinterRow({ printer }: { printer: Printer }) {
  const { engine, send, isPending } = useStore();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(printer.name);
  const [config, setConfig] = useState<AdapterConfig>(printer.config ?? {});
  const integrations = engine?.integrations ?? [];
  const meta = integrations.find((i) => i.id === printer.provider);
  const save = useSubmit(() => setConfig((draft) => withoutSecrets(meta, draft)));

  useEffect(() => setName(printer.name), [printer.id, printer.name]);
  useEffect(() => setConfig(printer.config ?? {}), [printer.id]);

  const dirty = name.trim() !== printer.name || JSON.stringify(config) !== JSON.stringify(printer.config ?? {});

  return (
    <div className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
        <span className={`led ${printer.online ? "led-on" : "led-off"}`} />
        <div className="min-w-0 grow basis-40 leading-tight">
          <div className="text-sm font-medium truncate">{printer.name}</div>
          <div className="mono text-[0.62rem] text-text-2 truncate">{providerLabel(integrations, printer.provider)}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <DeviceChip state={printer.device_state ?? undefined} />
          <button className="btn !py-1 !px-2.5 !text-[0.62rem]" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide" : "Edit"}
          </button>
          <button
            className="btn btn-danger !py-1 !px-2.5 !text-[0.62rem]"
            disabled={isPending("printer.remove", printer.id)}
            onClick={() => send({ cmd: "printer.remove", id: printer.id })}
          >
            {isPending("printer.remove", printer.id) ? "Removing…" : "Remove"}
          </button>
        </div>
      </div>
      {open && meta && (
        <div className="px-3 pb-3 pt-1 border-t border-line-0 space-y-3">
          <input className="field" aria-label="Name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <SchemaForm meta={meta} value={config} saved={printer.secrets_set} onChange={setConfig} />
          <PrinterTest id={printer.id} provider={printer.provider} config={config} />
          <button
            className="btn btn-primary w-full !py-1.5"
            disabled={!dirty || isPending("printer.update", printer.id)}
            onClick={() => save.submit({ cmd: "printer.update", id: printer.id, patch: { name: name.trim(), config } })}
          >
            {isPending("printer.update", printer.id) ? "Saving…" : "Save"}
          </button>
          {save.error && (
            <span role="alert" className="chip chip-message chip-bad">
              {save.error}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function RegisterPrinter() {
  const { engine, send, isPending } = useStore();
  const integrations = engine?.integrations ?? [];
  const [provider, setProvider] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<AdapterConfig>({});
  const meta = integrations.find((i) => i.id === provider);
  const busy = isPending("printer.add");
  const printers = engine?.printers.length ?? 0;
  const printersWhenSent = useRef<number | null>(null);

  useEffect(() => {
    if (busy || printersWhenSent.current === null) return;
    if (printers > printersWhenSent.current) {
      setProvider("");
      setName("");
      setConfig({});
    }
    printersWhenSent.current = null;
  }, [busy]);

  return (
    <div className="space-y-3">
      <select
        className="field"
        aria-label="Printer service"
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
          <input className="field" aria-label="Name" placeholder={`Name (e.g. ${meta.label} Ender 3)`} value={name} onChange={(e) => setName(e.target.value)} />
          <SchemaForm meta={meta} value={config} onChange={setConfig} />
          <PrinterTest id={NEW_PRINTER} provider={provider} config={config} />
          <button
            className="btn btn-primary w-full"
            disabled={busy}
            onClick={() => {
              printersWhenSent.current = printers;
              send({ cmd: "printer.add", printer: { name: name.trim(), provider, config } });
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
