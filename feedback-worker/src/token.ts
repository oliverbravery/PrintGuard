const encoder = new TextEncoder();

const signingKey = (secret: string) =>
  crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);

const toHex = (bytes: ArrayBuffer) => [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, "0")).join("");

const fromHex = (hex: string) => Uint8Array.from(hex.match(/../g) ?? [], (pair) => parseInt(pair, 16));

export const keyed = async (value: string, secret: string) =>
  toHex(await crypto.subtle.sign("HMAC", await signingKey(secret), encoder.encode(value)));

export async function issueToken(secret: string): Promise<string> {
  const hub = crypto.randomUUID().replaceAll("-", "");
  return `${hub}.${await keyed(hub, secret)}`;
}

export async function hubOf(token: string, secret: string): Promise<string | null> {
  const match = /^([0-9a-f]{32})\.([0-9a-f]{64})$/.exec(token);
  if (!match) return null;
  const [, hub, signature] = match;
  const genuine = await crypto.subtle.verify("HMAC", await signingKey(secret), fromHex(signature), encoder.encode(hub));
  return genuine ? hub : null;
}
