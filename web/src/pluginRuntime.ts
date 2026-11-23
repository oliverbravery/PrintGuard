import type { Finding } from "./lint";
import { log } from "./log";
import { withoutKeys } from "./optimistic";
import { PluginPanelHost } from "./panel";
import { commandAllowed, imageUrl, LINK_ACTIONS, normalise, outboundLink, outboundRequest, outboundSocket, PluginHost, projectEvent, projectState, type PluginTarget, type StoreChanges } from "./plugins";
import { play, playFile } from "./sound";
import { measureCover } from "./theme";
import type { EngineState, PluginEffect, PluginNode, PluginRecord } from "./types";

const MAX_NOTICE_CHARS = 200;

export interface PluginSlices {
  engine: EngineState | null;
  reconnecting: boolean;
  background: { id: string; image: string } | null;
  pluginTrees: Record<string, PluginNode | null>;
  pluginViews: Record<string, Record<string, PluginNode | null>>;
  pluginFindings: Record<string, Finding[]>;
  pluginPanels: Record<string, { html: string; assets: Record<string, Blob> }>;
  pluginAssets: Record<string, Record<string, string>>;
  pluginFailures: Record<string, string>;
  pluginPages: Record<string, Record<string, string>>;
  send(cmd: Record<string, unknown>): string | null;
  toast(kind: "info" | "alert" | "error", text: string): void;
}

type SlicePatch = Partial<PluginSlices> | ((state: PluginSlices) => Partial<PluginSlices>);

export function createPluginRuntime(
  get: () => PluginSlices,
  set: (patch: SlicePatch) => void,
  sendSilent: (cmd: Record<string, unknown>) => string,
  reconnectingMessage: string,
) {
  const hosts = new Map<string, PluginHost>();
  const panels = new Map<string, PluginPanelHost>();
  const codeRequests = new Map<string, string>();
  const unsavedStores = new Map<string, StoreChanges>();
  const configWrites = new Map<string, string>();
  const codeDigests = new Map<string, string>();

  const showBackground = (next: { id: string; image: string } | null) => {
    set({ background: next });
    void measureCover(next?.image ?? null);
  };

  const writeStore = (id: string) => {
    configWrites.set(sendSilent({ cmd: "plugin.update", id, patch: { store: unsavedStores.get(id) } }), id);
  };

  const pluginState = (plugin: PluginRecord) => {
    const engine = get().engine;
    return engine ? projectState(engine, plugin.granted, engine.plugin_permissions) : {};
  };

  const pluginTargets = (plugin: PluginRecord): PluginTarget[] =>
    plugin.manifest.surfaces
      .filter((surface) => surface === "monitor" || surface === "settings")
      .flatMap((surface) => (get().engine?.monitors ?? []).map((monitor) => ({ id: monitor.id, surface })));

  const dropHosts = (matches: (id: string) => boolean) => {
    for (const [id, host] of hosts) {
      if (!matches(id)) continue;
      host.close();
      hosts.delete(id);
    }
  };

  const perform = (id: string, effects: PluginEffect[]) => {
    const engine = get().engine;
    const plugin = engine?.plugins.find((p) => p.id === id);
    if (!engine || !plugin) return;
    for (const effect of effects) {
      if (effect.kind === "command" && effect.cmd) {
        const name = String(effect.cmd.cmd);
        if (!commandAllowed(name, plugin.granted, engine.plugin_permissions)) {
          get().toast("error", `${plugin.manifest.name} tried to run ${name} without permission`);
        } else if (get().reconnecting) get().toast("error", reconnectingMessage);
        else sendSilent(effect.cmd);
      } else if (effect.kind === "http" && effect.request) {
        sendSilent(outboundRequest(id, effect.request));
      } else if (effect.kind === "socket" && effect.request) {
        sendSilent(outboundSocket(id, String(effect.action), effect.request));
      } else if (effect.kind === "link" && effect.request && LINK_ACTIONS.includes(String(effect.action))) {
        sendSilent(outboundLink(id, String(effect.action), effect.request));
      } else if (effect.kind === "notify") {
        if (plugin.granted.includes("notify")) {
          get().toast("info", `${plugin.manifest.name}: ${String(effect.text ?? "").slice(0, MAX_NOTICE_CHARS)}`);
        }
      } else if (effect.kind === "sound") {
        const assets = get().pluginAssets[id];
        const file = effect.asset && assets && Object.hasOwn(assets, effect.asset) ? assets[effect.asset] : undefined;
        if (!plugin.granted.includes("sound")) continue;
        if (effect.asset) file && playFile(file);
        else play(effect.tones ?? []);
      } else if (effect.kind === "background") {
        if (!plugin.granted.includes("background")) continue;
        const image = imageUrl(effect.image);
        showBackground(image ? { id, image } : null);
      } else if (effect.kind === "view") {
        if (plugin.files.includes("panel.html")) set((s) => ({ pluginTrees: { ...s.pluginTrees, [id]: normalise(effect.tree) } }));
      } else if (effect.kind === "log") {
        log("info", `plugin ${id}:`, effect.text);
      }
    }
  };

  const handlers = {
    onView: (id: string, tree: PluginNode | null, targets: Record<string, PluginNode | null>) =>
      set((s) => ({
        pluginTrees: s.engine?.plugins.find((p) => p.id === id)?.files.includes("panel.html") ? s.pluginTrees : { ...s.pluginTrees, [id]: tree },
        pluginViews: { ...s.pluginViews, [id]: targets },
      })),
    onEffects: perform,
    onStore: (id: string, { written, removed }: StoreChanges) => {
      if (!removed.length && !Object.keys(written).length) return;
      const unsaved = unsavedStores.get(id) ?? { written: {}, removed: [] };
      unsavedStores.set(id, {
        written: { ...withoutKeys(unsaved.written, removed), ...written },
        removed: [...unsaved.removed.filter((key) => !(key in written)), ...removed],
      });
      writeStore(id);
    },
    onFailure: (id: string, failure: string) => {
      dropHosts((hosted) => hosted === id);
      set((s) => ({ pluginFailures: { ...s.pluginFailures, [id]: failure } }));
      get().toast("error", `Plugin ${id} stopped: ${failure}`);
    },
  };

  const forget = (id: string, keepPage: boolean) => {
    dropHosts((hosted) => hosted === id);
    panels.get(id)?.close();
    panels.delete(id);
    for (const url of Object.values(get().pluginAssets[id] ?? {})) URL.revokeObjectURL(url);
    for (const [reqId, requested] of codeRequests) if (requested === id) codeRequests.delete(reqId);
    codeDigests.delete(id);
    const drop = <T>(record: Record<string, T>) => withoutKeys(record, [id]);
    set((s) => ({
      pluginPanels: drop(s.pluginPanels),
      pluginFindings: drop(s.pluginFindings),
      pluginAssets: drop(s.pluginAssets),
      pluginTrees: drop(s.pluginTrees),
      pluginViews: drop(s.pluginViews),
      pluginFailures: drop(s.pluginFailures),
      pluginPages: keepPage ? s.pluginPages : drop(s.pluginPages),
    }));
  };

  const read = async (id: string, sources: Record<string, string>) => {
    const engine = get().engine;
    const plugin = engine?.plugins.find((p) => p.id === id);
    if (!engine || !plugin) return;
    const { lint } = await import("./lint");
    const findings = lint(plugin.manifest, sources, engine.plugin_permissions, engine.plugin_event_permissions);
    set((s) => ({ pluginFindings: { ...s.pluginFindings, [id]: findings } }));
  };

  const start = (id: string, sources: Record<string, string>, assets: Record<string, string>) => {
    const engine = get().engine;
    const plugin = engine?.plugins.find((p) => p.id === id);
    if (!engine || !plugin || !plugin.enabled) return;
    const types = engine.plugin_assets ?? {};
    const blobs: Record<string, Blob> = {};
    const files: Record<string, string> = {};
    const text: Record<string, string> = {};
    for (const [name, data] of Object.entries(assets)) {
      const ext = name.split(".").pop() ?? "";
      const type = Object.hasOwn(types, ext) ? types[ext] : undefined;
      if (!type) continue;
      const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
      blobs[name] = new Blob([bytes], { type });
      if (type.startsWith("text/") || type === "application/json") text[name] = new TextDecoder().decode(bytes);
      else files[name] = URL.createObjectURL(blobs[name]);
    }
    for (const url of Object.values(get().pluginAssets[id] ?? {})) URL.revokeObjectURL(url);
    set((s) => ({ pluginAssets: { ...s.pluginAssets, [id]: files } }));
    set((s) => ({ pluginFailures: withoutKeys(s.pluginFailures, [id]) }));
    if (sources["panel.html"]) {
      set((s) => ({ pluginPanels: { ...s.pluginPanels, [id]: { html: sources["panel.html"], assets: blobs } } }));
    }
    if (!hosts.has(id) && sources["plugin.js"]) {
      const host = new PluginHost(plugin, sources["plugin.js"], text, handlers);
      hosts.set(id, host);
      void host.update(pluginState(plugin), pluginTargets(plugin));
    }
  };

  return {
    perform,
    dropInFlight() {
      codeRequests.clear();
      configWrites.clear();
    },
    resendUnsaved() {
      for (const id of unsavedStores.keys()) writeStore(id);
    },
    onStateAck(reqId: string | undefined) {
      if (reqId === undefined) return;
      const answeredWrite = configWrites.get(reqId);
      configWrites.delete(reqId);
      if (answeredWrite && ![...configWrites.values()].includes(answeredWrite)) unsavedStores.delete(answeredWrite);
    },
    onError(reqId: string | undefined) {
      if (reqId === undefined) return;
      unsavedStores.delete(configWrites.get(reqId) ?? "");
      configWrites.delete(reqId);
    },
    onCode(reqId: string, id: string, sources: Record<string, string>, assets: Record<string, string>) {
      if (codeRequests.get(reqId) !== id) return;
      codeRequests.delete(reqId);
      codeDigests.set(id, JSON.stringify(get().engine?.plugins.find((p) => p.id === id)?.digests));
      void read(id, sources);
      start(id, sources, assets);
    },
    forward(id: string, event: Record<string, unknown>) {
      const engine = get().engine;
      const plugin = engine?.plugins.find((p) => p.id === id);
      if (!engine || !plugin) return;
      const seen = projectEvent(event, engine.plugin_events, plugin.granted, engine.plugin_permissions, engine.plugin_event_permissions);
      if (!seen) return;
      void hosts.get(id)?.event(seen, pluginState(plugin), pluginTargets(plugin));
      panels.get(id)?.event(seen);
    },
    sync(engine: EngineState) {
      const held = new Set([...hosts.keys(), ...panels.keys(), ...codeDigests.keys(), ...Object.keys(get().pluginPages), ...Object.keys(get().pluginAssets)]);
      for (const id of held) {
        const plugin = engine.plugins.find((p) => p.id === id);
        if (!plugin) {
          forget(id, false);
          unsavedStores.delete(id);
        } else if (codeDigests.has(id) && codeDigests.get(id) !== JSON.stringify(plugin.digests)) forget(id, true);
      }
      const wanted = new Set(engine.plugins.filter((p) => p.enabled && p.files.includes("plugin.js")).map((p) => p.id));
      dropHosts((id) => !wanted.has(id));
      if (get().background && !engine.plugins.some((p) => p.id === get().background?.id && p.enabled)) showBackground(null);
      for (const [id, panel] of panels) {
        if (engine.plugins.some((p) => p.id === id && p.enabled)) continue;
        panel.close();
        panels.delete(id);
        set((s) => ({ pluginPanels: withoutKeys(s.pluginPanels, [id]) }));
      }
      const stale = Object.keys(get().pluginFailures).filter((id) => !engine.plugins.some((p) => p.id === id && p.enabled));
      if (stale.length) set((s) => ({ pluginFailures: withoutKeys(s.pluginFailures, stale) }));
      const missing = new Set(
        [
          ...[...wanted].filter((id) => !hosts.has(id)),
          ...engine.plugins.filter((p) => p.enabled && p.files.includes("panel.html") && !get().pluginPanels[p.id]).map((p) => p.id),
          ...engine.plugins.filter((p) => p.enabled && p.granted.includes("sound") && !get().pluginAssets[p.id]).map((p) => p.id),
        ].filter((id) => !get().pluginFailures[id]),
      );
      for (const id of missing) {
        if ([...codeRequests.values()].includes(id)) continue;
        codeRequests.set(sendSilent({ cmd: "plugin.code", id }), id);
      }
      for (const [id, host] of hosts) {
        const plugin = engine.plugins.find((p) => p.id === id);
        if (!plugin) continue;
        void host.update(pluginState(plugin), pluginTargets(plugin), unsavedStores.has(plugin.id) ? undefined : plugin.config);
      }
      for (const [id, panel] of panels) {
        const plugin = engine.plugins.find((p) => p.id === id);
        if (plugin) panel.update(pluginState(plugin), plugin.secrets_set);
      }
    },
    act(id: string, action: string, arg: unknown, toPanel = false) {
      if (toPanel) return panels.get(id)?.act(action, arg);
      const plugin = get().engine?.plugins.find((p) => p.id === id);
      const host = hosts.get(id);
      if (plugin && host) void host.act(action, arg, pluginState(plugin), pluginTargets(plugin));
    },
    mountPanel(id: string, container: HTMLElement | null) {
      panels.get(id)?.close();
      panels.delete(id);
      const engine = get().engine;
      const plugin = engine?.plugins.find((p) => p.id === id);
      const source = get().pluginPanels[id];
      if (!container || !engine || !plugin || !source) return;
      panels.set(id, new PluginPanelHost(plugin, container, source.html, source.assets, pluginState(plugin), handlers));
    },
    check(id: string) {
      if (get().pluginFindings[id] || [...codeRequests.values()].includes(id)) return;
      const reqId = get().send({ cmd: "plugin.code", id });
      if (reqId) codeRequests.set(reqId, id);
    },
  };
}
