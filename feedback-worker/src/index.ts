import { z } from "zod";
import { Gate, type Refusal } from "./gate";
import { DAY_MS, EXPIRY_DAYS, EXPIRY_WARN_DAYS, FRAME_BYTES_MAX, STORED_BYTES_MAX, STORED_BYTES_WARN } from "./limits";
import { hubOf, issueToken, keyed } from "./token";

export { Gate };

const frameId = z.string().regex(/^[0-9a-f]{12}$/);

const FrameDetails = z.object({
  print: frameId,
  frame: frameId,
  label: z.enum(["good", "failure"]),
  kind: z.enum(["alert", "near", "spaced"]),
  score: z.number().min(0).max(1),
  threshold: z.number().min(0).max(1),
  ts: z.number(),
  version: z.string().max(20),
  provider: z.string().max(40),
  printer: z.string().max(80),
});

const refuse = ({ status, code, retryAt }: Refusal) =>
  Response.json(
    { code, retry_at: retryAt },
    { status, headers: retryAt ? { "Retry-After": String(Math.max(1, Math.ceil(retryAt - Date.now() / 1000))) } : {} },
  );

export function networkOf(address: string): string {
  if (!address.includes(":")) return address;
  const [head, tail = ""] = address.split("::");
  const leading = head.split(":").filter(Boolean);
  const trailing = tail.split(":").filter(Boolean);
  const groups = [...leading, ...Array<string>(8 - leading.length - trailing.length).fill("0"), ...trailing];
  return groups.slice(0, 3).map((group) => parseInt(group, 16).toString(16)).join(":");
}

const callerNetwork = (request: Request, env: Env) =>
  keyed(networkOf(request.headers.get("CF-Connecting-IP") ?? "unknown"), env.TOKEN_SECRET);

const parseDetails = (header: string | null) => {
  try {
    return FrameDetails.safeParse(JSON.parse(header ?? ""));
  } catch {
    return FrameDetails.safeParse(null);
  }
};

const sentByABrowser = (request: Request) =>
  request.headers.has("Origin") || request.headers.get("Content-Type") !== "application/json";

async function register(request: Request, env: Env): Promise<Response> {
  if (sentByABrowser(request)) return refuse({ status: 403, code: "browser" });
  const refusal = await env.GATE.getByName("gate").register(await callerNetwork(request, env));
  if (refusal) return refuse(refusal);
  return Response.json({ token: await issueToken(env.TOKEN_SECRET) }, { status: 201 });
}

async function storeFrame(request: Request, env: Env): Promise<Response> {
  const hub = await hubOf((request.headers.get("Authorization") ?? "").replace(/^Bearer /, ""), env.TOKEN_SECRET);
  if (!hub) return refuse({ status: 401, code: "token" });
  const declaredBytes = Number(request.headers.get("Content-Length"));
  if (!(declaredBytes > 0)) return refuse({ status: 411, code: "length" });
  if (declaredBytes > FRAME_BYTES_MAX) return refuse({ status: 413, code: "too_large" });
  const details = parseDetails(request.headers.get("X-Frame"));
  if (!details.success) return refuse({ status: 400, code: "details" });
  const jpeg = new Uint8Array(await request.arrayBuffer());
  if (jpeg.byteLength > FRAME_BYTES_MAX) return refuse({ status: 413, code: "too_large" });
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8 || jpeg[2] !== 0xff) return refuse({ status: 415, code: "not_jpeg" });

  const gate = env.GATE.getByName("gate");
  const network = await callerNetwork(request, env);
  const { print, frame, ...labels } = details.data;
  const key = `${hub}/${print}/${frame}.jpg`;
  const reserved = await gate.reserve(hub, network, key, jpeg.byteLength, (await env.FRAMES.head(key))?.size ?? 0);
  if ("code" in reserved) return refuse(reserved);
  try {
    await env.FRAMES.put(key, jpeg, {
      httpMetadata: { contentType: "image/jpeg" },
      customMetadata: Object.fromEntries(Object.entries(labels).map(([name, value]) => [name, String(value)])),
    });
  } catch (error) {
    await gate.release(hub, network, key, reserved);
    throw error;
  }
  return Response.json({}, { status: 201 });
}

export function reminders(inbox: { bytes: number; expiring: number }): string[] {
  const lines: string[] = [];
  if (inbox.expiring > 0) lines.push(`${inbox.expiring} frames expire within ${EXPIRY_WARN_DAYS} days.`);
  if (inbox.bytes >= STORED_BYTES_WARN) lines.push(`The inbox is ${Math.round((100 * inbox.bytes) / STORED_BYTES_MAX)}% full.`);
  return lines;
}

export const expiresSoon = (uploaded: Date, now: number) =>
  uploaded.getTime() <= now - (EXPIRY_DAYS - EXPIRY_WARN_DAYS) * DAY_MS;

async function recountAndRemind(env: Env): Promise<void> {
  const gate = env.GATE.getByName("gate");
  const now = Date.now();
  const inbox = { bytes: 0, expiring: 0 };
  await gate.beginRecount();
  let cursor: string | undefined;
  do {
    const page = await env.FRAMES.list({ cursor });
    for (const object of page.objects) {
      inbox.bytes += object.size;
      if (expiresSoon(object.uploaded, now)) inbox.expiring += 1;
    }
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  await gate.recount(inbox.bytes);
  const lines = reminders(inbox);
  if (lines.length === 0) return;
  await env.EMAIL.send({
    to: env.REMINDER_TO,
    from: env.REMINDER_FROM,
    subject: "PrintGuard feedback inbox needs pulling",
    text: [...lines, "Run the pull script."].join("\n"),
  });
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (env.ACCEPTING !== "true") return refuse({ status: 503, code: "closed" });
    if (request.method === "POST" && pathname === "/register") return register(request, env);
    if (request.method === "PUT" && pathname === "/frame") return storeFrame(request, env);
    return new Response(null, { status: 404 });
  },
  async scheduled(_controller, env) {
    await recountAndRemind(env);
  },
} satisfies ExportedHandler<Env>;
