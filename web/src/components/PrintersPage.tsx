import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router";
import { useShallow } from "zustand/react/shallow";
import { useStore } from "../store";
import { useCreated, useSubmit } from "../submit";
import type { AdapterConfig, AdapterMeta, Printer } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { Dialog } from "./Dialog";
import { AddCell, DetailHead, ListHead, Page, Split } from "./Page";
import { retypeReason, SchemaForm, savedSecretTitles } from "./SchemaForm";
import { DeviceStatus, Status } from "./Status";
import { TestRow } from "./TestRow";

const NEW_PRINTER = "new";

function providerLabel(integrations: AdapterMeta[], id: string): string {
  return integrations.find((i) => i.id === id)?.label ?? id;
}

function PrinterTest({ id, provider, config }: { id: string; provider: string; config: AdapterConfig }) {
  const { printerTest, testing, testPrinter } = useStore(
    useShallow((s) => ({ printerTest: s.printerTest, testing: s.testing, testPrinter: s.testPrinter })),
  );
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

function PrinterModelField({ value, onChange }: { value: string; onChange: (model: string) => void }) {
  return (
    <label className="block">
      <span className="label mb-1 block">Printer model</span>
      <input className="field" placeholder="Optional, e.g. Prusa MK4" maxLength={80} value={value} onChange={(e) => onChange(e.target.value)} />
      <span className="mt-1 block text-xs text-text-2">Included when you share reviewed frames from this printer to help train future models.</span>
    </label>
  );
}

function PrinterEditor({ printer }: { printer: Printer }) {
  const { savedIntegrations, send, removing, saving } = useStore(
    useShallow((s) => ({
      savedIntegrations: s.engine?.integrations,
      send: s.send,
      removing: s.isPending("printer.remove", printer.id),
      saving: s.isPending("printer.update", printer.id),
    })),
  );
  const integrations = savedIntegrations ?? [];
  const [name, setName] = useState(printer.name);
  const [model, setModel] = useState(printer.model ?? "");
  const [config, setConfig] = useState<AdapterConfig>(printer.config ?? {});
  const meta = integrations.find((i) => i.id === printer.provider);
  const save = useSubmit(() => setConfig(printer.config ?? {}));

  useEffect(() => setName(printer.name), [printer.id, printer.name]);
  useEffect(() => setModel(printer.model ?? ""), [printer.id, printer.model]);
  useEffect(() => setConfig(printer.config ?? {}), [printer.id]);

  const retype = meta ? retypeReason(config, printer.config ?? {}, savedSecretTitles(meta, printer.secrets_set ?? [])) : null;
  const dirty = name.trim() !== printer.name || model.trim() !== (printer.model ?? "") || JSON.stringify(config) !== JSON.stringify(printer.config ?? {});

  return (
    <>
      <DetailHead title={printer.name}>
        <ConfirmButton disabled={removing} onConfirm={() => send({ cmd: "printer.remove", id: printer.id })}>
          {removing ? "Removing…" : "Remove"}
        </ConfirmButton>
      </DetailHead>
      <div className="mono flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line-0 px-4 py-2 text-xs">
        <Status tone={printer.online ? "ok" : "bad"}>{printer.online ? "online" : "offline"}</Status>
        <span className="text-text-1">{providerLabel(integrations, printer.provider)}</span>
        <DeviceStatus state={printer.device_state} />
      </div>
      {meta && (
        <div className="max-w-xl space-y-4 px-4 py-4">
          <label className="block">
            <span className="label mb-1 block">Name</span>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <PrinterModelField value={model} onChange={setModel} />
          <SchemaForm meta={meta} value={config} stored={printer.config ?? {}} saved={printer.secrets_set} onChange={setConfig} />
          <PrinterTest id={printer.id} provider={printer.provider} config={config} />
          <button
            className="btn btn-primary"
            disabled={!dirty || retype !== null || saving}
            onClick={() => save.submit({ cmd: "printer.update", id: printer.id, patch: { name: name.trim(), model: model.trim(), config } })}
          >
            {saving ? "Saving…" : "Save printer"}
          </button>
          {retype && <span className="block text-sm text-text-2">{retype}</span>}
          {save.error && (
            <span role="alert" className="chip chip-message chip-bad">
              {save.error}
            </span>
          )}
        </div>
      )}
    </>
  );
}

export function PrinterDialog() {
  const { engine, send, busy, openDialog } = useStore(
    useShallow((s) => ({
      engine: s.engine,
      send: s.send,
      busy: s.isPending("printer.add"),
      openDialog: s.openDialog,
    })),
  );
  const navigate = useNavigate();
  const integrations = engine?.integrations ?? [];
  const printers = engine?.printers ?? [];
  const [provider, setProvider] = useState("");
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [config, setConfig] = useState<AdapterConfig>({});
  const meta = integrations.find((i) => i.id === provider);

  useCreated("printer.add", printers, (added) => {
    openDialog(null);
    navigate(`/printers/${added.id}`);
  });

  const required = meta?.schema.required ?? [];
  const incomplete = required.some((key) => !String(config[key] ?? meta?.schema.properties[key]?.default ?? "").trim());

  return (
    <Dialog title="Register a printer" onClose={() => openDialog(null)}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!meta || busy || incomplete) return;
          send({ cmd: "printer.add", printer: { name: name.trim(), model: model.trim(), provider, config } });
        }}
      >
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
            <label className="block">
              <span className="label mb-1 block">Name</span>
              <input className="field" placeholder={`e.g. ${meta.label} Ender 3`} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <PrinterModelField value={model} onChange={setModel} />
            <SchemaForm meta={meta} value={config} onChange={setConfig} />
            <PrinterTest id={NEW_PRINTER} provider={provider} config={config} />
            <button type="submit" className="btn btn-primary" disabled={busy || incomplete}>
              {busy ? "Registering…" : "Register printer"}
            </button>
          </>
        )}
      </form>
    </Dialog>
  );
}

export function PrintersPage() {
  const { printerId } = useParams();
  const engine = useStore((s) => s.engine);
  const integrations = engine?.integrations ?? [];
  const printers = engine?.printers ?? [];
  const openDialog = useStore((s) => s.openDialog);
  const chosen = printers.find((printer) => printer.id === printerId);
  if (printerId && !chosen) return <Navigate to="/printers" replace />;
  const selected = chosen ?? printers[0];
  const list = (
    <>
      <ListHead title={`Printers · ${printers.length}`} action={<AddCell label="Add printer" onClick={() => openDialog("printer")} />} />
      {printers.map((printer) => (
        <Link key={printer.id} to={`/printers/${printer.id}`} aria-current={printer.id === selected?.id ? "page" : undefined} className="list-row">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{printer.name}</span>
            <span className="mono block truncate text-xs text-text-2">{providerLabel(integrations, printer.provider)}</span>
          </span>
          {printer.online ? <DeviceStatus state={printer.device_state} /> : <Status tone="bad">offline</Status>}
        </Link>
      ))}
    </>
  );
  const detail = selected ? (
    <PrinterEditor key={selected.id} printer={selected} />
  ) : (
    <>
      <DetailHead title="No printers" />
      <p className="px-4 py-4 text-sm text-text-2">Press + Add to register one.</p>
    </>
  );
  return (
    <Page title="Printers" phoneBack={printerId ? { to: "/printers", label: "Back" } : undefined} subview={Boolean(printerId)}>
      <Split list={list} detail={detail} detailShown={Boolean(printerId)} />
    </Page>
  );
}
