const SCHEMES = ["http", "https", "ws", "wss", "rtsp", "rtsps"];
const WILDCARD_SCHEMES = ["http", "https"];
const DEFAULT_PORTS: Record<string, number> = { http: 80, https: 443, ws: 80, wss: 443, rtsp: 554, rtsps: 322 };
const LOCAL_HOSTNAMES = ["localhost"];
const LOCAL_SUFFIXES = [".local", ".localhost", ".internal", ".home", ".lan"];
const PRIVATE_V4 = /^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|0\.)/;

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
  const match = PATTERN.exec(raw.trim().toLowerCase());
  return match ? { scheme: match[1], host: match[2], port: match[3] ?? "*", path: match[4] } : null;
}

function matchesHost(pattern: string, host: string): boolean {
  if (pattern === "*") return true;
  if (pattern.startsWith("*.")) return host === pattern.slice(2) || host.endsWith(pattern.slice(1));
  return host === pattern;
}

function matchesPath(pattern: string, path: string): boolean {
  const escaped = pattern.split("*").map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`^${escaped.join(".*?")}$`).test(path);
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

export function isLocalAddress(host: string): boolean {
  const bare = host.replace(/^\[|\]$/g, "");
  if (bare.includes(":")) return bare === "::1" || /^f[cd]/.test(bare);
  if (/^\d+\.\d+\.\d+\.\d+$/.test(bare)) return PRIVATE_V4.test(bare);
  return LOCAL_HOSTNAMES.includes(bare) || LOCAL_SUFFIXES.some((suffix) => bare.endsWith(suffix));
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
