const SCHEMES = ["http", "https", "ws", "wss", "rtsp", "rtsps"];
const WILDCARD_SCHEMES = ["http", "https"];
const DEFAULT_PORTS: Record<string, number> = { http: 80, https: 443, ws: 80, wss: 443, rtsp: 554, rtsps: 322 };
const LOCAL_HOSTNAMES = ["localhost"];
const LOCAL_SUFFIXES = [".local", ".localhost", ".internal", ".home", ".lan"];
const LOCAL_V4 = [
  "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
  "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4",
].map(prefix);
const GLOBAL_V4 = ["192.0.0.9/32", "192.0.0.10/32"].map(prefix);
const LOCAL_V6 = [
  "::1/128", "::/128", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32", "2002::/16", "3fff::/20", "fc00::/7", "fe80::/10",
].map(prefix);
const GLOBAL_V6 = ["2001:1::1/128", "2001:1::2/128", "2001:3::/32", "2001:4:112::/48", "2001:20::/28", "2001:30::/28"].map(prefix);
const MAPPED_V4 = prefix("::ffff:0:0/96");

const PATTERN = new RegExp(
  `^(\\*|${SCHEMES.join("|")})://` +
    `(\\*|(?:\\*\\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\\[[0-9a-f:]+\\])` +
    `(?::(\\*|\\d{1,5}))?` +
    `(/[^\\s]*)$`,
);

export interface UrlPattern {
  scheme: string;
  host: string;
  port: string;
  path: string;
}

export function parse(raw: string): UrlPattern | null {
  const match = PATTERN.exec(raw.trim().replace(/^[^/]*\/\/[^/]*/, (origin) => origin.toLowerCase()));
  return match ? { scheme: match[1], host: match[2], port: match[3] ?? "*", path: match[4] } : null;
}

function matchesHost(pattern: string, host: string): boolean {
  if (pattern === "*") return true;
  if (pattern.startsWith("*.")) return host === pattern.slice(2) || host.endsWith(pattern.slice(1));
  return host === pattern;
}

function matchesPath(pattern: string, path: string): boolean {
  const [first, ...middle] = pattern.split("*");
  const last = middle.pop();
  if (last === undefined) return path === first;
  const end = path.length - last.length;
  if (!path.startsWith(first) || end < first.length || !path.endsWith(last)) return false;
  let at = first.length;
  for (const piece of middle) {
    const found = path.indexOf(piece, at);
    if (found < 0 || found + piece.length > end) return false;
    at = found + piece.length;
  }
  return true;
}

export function matches(pattern: string, url: string): boolean {
  const rule = parse(pattern);
  if (!rule) return false;
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  const scheme = parsed.protocol.replace(":", "");
  const allowed = rule.scheme === "*" ? WILDCARD_SCHEMES : [rule.scheme];
  if (!parsed.hostname || !allowed.includes(scheme)) return false;
  const port = parsed.port ? Number(parsed.port) : (DEFAULT_PORTS[scheme] ?? 0);
  if (rule.port !== "*" && Number(rule.port) !== port) return false;
  const path = (parsed.pathname || "/") + parsed.search;
  return matchesHost(rule.host, parsed.hostname.toLowerCase()) && matchesPath(rule.path, path);
}

export function allowed(url: string, patterns: string[]): boolean {
  return patterns.some((pattern) => matches(pattern, url));
}

function bits(address: string): string {
  if (!address.includes(":")) return address.split(".").map((octet) => Number(octet).toString(2).padStart(8, "0")).join("");
  const [before, after] = address.split("::").map((run) => (run ? run.split(":") : []));
  const groups = [...before, ...Array(8 - before.length - (after ?? []).length).fill("0"), ...(after ?? [])];
  return groups.map((group) => parseInt(group, 16).toString(2).padStart(16, "0")).join("");
}

function prefix(network: string): string {
  const [address, length] = network.split("/");
  return bits(address).slice(0, Number(length));
}

function within(address: string, networks: string[]): boolean {
  return networks.some((network) => address.startsWith(network));
}

function literalAddress(host: string): string | null {
  try {
    const written = new URL(`http://${host}`).hostname.replace(/^\[|\]$/g, "");
    return written.includes(":") || /^\d+\.\d+\.\d+\.\d+$/.test(written) ? bits(written) : null;
  } catch {
    return null;
  }
}

export function isLocalAddress(host: string): boolean {
  const address = literalAddress(host);
  if (address === null) return LOCAL_HOSTNAMES.includes(host) || LOCAL_SUFFIXES.some((suffix) => host.endsWith(suffix));
  if (address.length === 128 && !address.startsWith(MAPPED_V4)) return within(address, LOCAL_V6) && !within(address, GLOBAL_V6);
  return within(address.slice(-32), LOCAL_V4) && !within(address.slice(-32), GLOBAL_V4);
}

export function reachesLocal(pattern: string): boolean {
  const rule = parse(pattern);
  return rule !== null && (rule.host === "*" || isLocalAddress(rule.host.replace(/^\*\./, "")));
}

export function webUrl(raw: string): string | null {
  try {
    const url = new URL(String(raw));
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export function phrase(pattern: string): string {
  const rule = parse(pattern);
  if (!rule) return pattern;
  const where =
    rule.host === "*"
      ? "any address at all"
      : rule.host.startsWith("*.")
        ? `${rule.host.slice(2)} and its subdomains`
        : rule.host;
  const port = rule.port === "*" ? "" : ` on port ${rule.port}`;
  const what = rule.path === "/*" ? "anything on" : `${rule.path.replace(/\*+$/, "")} on`;
  return `${what} ${where}${port}`;
}

export function openIn(tab: Window | null, raw: string): void {
  const url = webUrl(raw);
  if (!tab || !url) {
    tab?.close();
    openExternally(raw);
    return;
  }
  tab.opener = null;
  tab.location.replace(url);
}

function openExternally(raw: string): void {
  const url = webUrl(raw);
  if (!url) return;
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
