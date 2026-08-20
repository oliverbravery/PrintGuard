import { parse } from "acorn";
import { simple } from "acorn-walk";
import type { Permission, PluginManifest } from "./types";
import { matches } from "./urls.ts";

export interface Finding {
  kind: "unused" | "undeclared" | "dynamic";
  what: string;
}

interface Call {
  permission: string | null;
  url: string | null;
  link: { kind: string; name: string } | null;
  dynamic: string | null;
}

const CTX_PERMISSIONS: Record<string, string> = { notify: "notify", sound: "sound", background: "background" };
const PLUGIN_PERMISSIONS: Record<string, string> = { route: "routes", gate: "gate", serve: "link:provide" };
const NETWORK_CALLS = ["http", "socket"];
const LINK_CALLS: Record<string, string> = { call: "link:consume", publish: "link:provide" };
const STATE_COLLECTIONS = ["monitors", "cameras", "printers"];
const EVENT_PERMISSIONS: Record<string, string> = { state: "state:read", frame: "camera:frames", history: "history:read" };
const SECRET_REFERENCE = /\{\{\s*secret\.([a-z0-9_-]{1,40})\s*\}\}/g;

function literalField(node: any, field: string): string | null {
  const argument = node.arguments?.[0];
  if (argument?.type !== "ObjectExpression") return null;
  const property = argument.properties.find((p: any) => p.key?.name === field || p.key?.value === field);
  if (!property) return null;
  if (property.value.type === "Literal" && typeof property.value.value === "string") return property.value.value;
  if (property.value.type === "TemplateLiteral" && property.value.expressions.length === 0) {
    return property.value.quasis[0].value.cooked;
  }
  return null;
}

function scriptsIn(html: string): string {
  return [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map((found) => found[1]).join("\n;\n");
}

function callsIn(code: string, commands: Record<string, string>, owners: string[]): { calls: Call[]; secrets: string[]; failed: string | null } {
  const calls: Call[] = [];
  const secrets: string[] = [];
  let tree: any;
  try {
    tree = parse(code, { ecmaVersion: "latest", allowReturnOutsideFunction: true });
  } catch (err) {
    return { calls, secrets, failed: err instanceof Error ? err.message : String(err) };
  }

  simple(tree, {
    Literal(node: any) {
      if (typeof node.value === "string") {
        for (const found of node.value.matchAll(SECRET_REFERENCE)) secrets.push(found[1]);
      }
    },
    TemplateElement(node: any) {
      for (const found of String(node.value.cooked ?? "").matchAll(SECRET_REFERENCE)) secrets.push(found[1]);
    },
    MemberExpression(node: any) {
      const inner = node.object;
      if (inner?.type === "MemberExpression" && owners.includes(inner.object?.name) && inner.property?.name === "state") {
        if (STATE_COLLECTIONS.includes(node.property?.name)) calls.push({ permission: "state:read", url: null, link: null, dynamic: null });
      }
    },
    CallExpression(node: any) {
      const callee = node.callee;
      if (callee?.type !== "MemberExpression") return;
      const owner = callee.object?.name;
      const method = callee.property?.name;
      if (owner === "plugin" && PLUGIN_PERMISSIONS[method]) {
        calls.push({ permission: PLUGIN_PERMISSIONS[method], url: null, link: null, dynamic: null });
      }
      if (owner === "plugin" || owners.includes(owner)) {
        if (method === "on" && node.arguments?.[0]?.type === "Literal") {
          const implied = EVENT_PERMISSIONS[String(node.arguments[0].value)];
          if (implied) calls.push({ permission: implied, url: null, link: null, dynamic: null });
        }
      }
      if (!owners.includes(owner)) return;
      if (CTX_PERMISSIONS[method]) calls.push({ permission: CTX_PERMISSIONS[method], url: null, link: null, dynamic: null });
      if (method === "command") {
        const named = literalField(node, "cmd");
        calls.push({ permission: named ? (commands[named] ?? null) : null, url: null, link: null, dynamic: named ? null : "a command it builds as it runs" });
        if (named && !commands[named]) calls.push({ permission: null, url: null, link: null, dynamic: `an unknown command, ${named}` });
      }
      if (LINK_CALLS[method]) {
        const to = method === "call" ? literalField(node, "to") : null;
        const channel = literalField(node, "channel");
        const named = method === "call" ? (to && channel ? `${to}:${channel}` : null) : channel;
        calls.push({
          permission: LINK_CALLS[method],
          url: null,
          link: named ? { kind: method, name: named } : null,
          dynamic: named ? null : `a plugin channel it names as it runs`,
        });
      }
      if (NETWORK_CALLS.includes(method)) {
        const url = literalField(node, "url");
        calls.push({ permission: "net", url, link: null, dynamic: url ? null : "an address it builds as it runs" });
      }
    },
  });
  return { calls, secrets, failed: null };
}

export function lint(manifest: PluginManifest, sources: Record<string, string>, permissions: Permission[]): Finding[] {
  const commands = Object.fromEntries(
    permissions.flatMap((permission) => (permission.commands ?? []).map((command) => [command, permission.id])),
  );
  const findings: Finding[] = [];
  const calls: Call[] = [];
  const secrets: string[] = [];

  for (const [name, code] of Object.entries(sources)) {
    const panel = name.endsWith(".html");
    const read = callsIn(panel ? scriptsIn(code) : code, commands, panel ? ["pg"] : ["ctx"]);
    if (read.failed) findings.push({ kind: "dynamic", what: `${name} could not be read, ${read.failed}` });
    calls.push(...read.calls);
    secrets.push(...read.secrets);
  }

  const wanted = new Set(calls.map((call) => call.permission).filter(Boolean) as string[]);
  const declared = new Set(manifest.permissions);
  if (manifest.consumes.length) wanted.add("link:consume");
  if (Object.keys(manifest.provides).length) wanted.add("link:provide");
  const local = manifest.urls.some((url) => url.includes("://*") || url.includes("://localhost") || url.includes("://127."));
  for (const event of manifest.events) {
    if (EVENT_PERMISSIONS[event]) wanted.add(EVENT_PERMISSIONS[event]);
  }

  for (const permission of wanted) {
    if (!declared.has(permission)) findings.push({ kind: "undeclared", what: permission });
  }
  for (const permission of declared) {
    const implied = permission === "net:local" ? wanted.has("net") && local : permission === "oauth" || permission === "camera:view";
    if (!wanted.has(permission) && !implied) findings.push({ kind: "unused", what: permission });
  }
  for (const call of calls) {
    if (call.url && !manifest.urls.some((pattern) => matches(pattern, call.url as string))) {
      findings.push({ kind: "undeclared", what: call.url });
    }
  }
  for (const call of calls) {
    if (!call.link) continue;
    const declared = call.link.kind === "call" ? manifest.consumes.includes(call.link.name) : call.link.name in manifest.provides;
    if (!declared) findings.push({ kind: "undeclared", what: call.link.name });
  }
  for (const name of new Set(secrets)) {
    if (!(name in manifest.secrets) && !name.startsWith("oauth")) findings.push({ kind: "undeclared", what: `{{secret.${name}}}` });
  }
  for (const what of new Set(calls.map((call) => call.dynamic).filter(Boolean) as string[])) {
    findings.push({ kind: "dynamic", what });
  }
  return findings;
}

export function phraseFinding(finding: Finding): string {
  if (finding.kind === "unused") return `Asks for ${finding.what} but never uses it.`;
  if (finding.kind === "undeclared") return `Uses ${finding.what} without asking for it, so PrintGuard will refuse it.`;
  return `Uses ${finding.what}, so nobody can tell from the code what it reaches.`;
}
