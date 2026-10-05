import { createScheduledController } from "cloudflare:test";
import { env, exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import worker, { expiresSoon, networkOf, reminders } from "../src";
import {
  DAY_MS,
  EXPIRY_DAYS,
  EXPIRY_WARN_DAYS,
  FRAME_BYTES_MAX,
  REGISTRATIONS_PER_NETWORK,
  STORED_BYTES_MAX,
  STORED_BYTES_WARN,
  UPLOADS_PER_DAY,
  UPLOADS_PER_HUB,
  UPLOADS_PER_NETWORK,
} from "../src/limits";
import { issueToken } from "../src/token";

const ORIGIN = "https://feedback.example";
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4]);

const details = (frame: string, changes: Record<string, unknown> = {}) => ({
  print: "aaaaaaaaaaaa",
  frame,
  label: "good",
  kind: "spaced",
  score: 0.12,
  threshold: 0.75,
  ts: 1_791_000_000,
  version: "2.6.0",
  provider: "moonraker",
  printer: "Voron 2.4",
  ...changes,
});

const frameId = (index: number) => index.toString(16).padStart(12, "0");

const register = (address: string, headers: Record<string, string> = { "Content-Type": "application/json" }) =>
  exports.default.fetch(`${ORIGIN}/register`, { method: "POST", headers: { "CF-Connecting-IP": address, ...headers }, body: "{}" });

const upload = (token: string, address: string, frame: string, body: Uint8Array = JPEG, changes: Record<string, unknown> = {}) =>
  exports.default.fetch(`${ORIGIN}/frame`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "CF-Connecting-IP": address,
      "Content-Type": "image/jpeg",
      "Content-Length": String(body.byteLength),
      "X-Frame": JSON.stringify(details(frame, changes)),
    },
    body,
  });

const code = async (response: Response) => ((await response.json()) as { code: string }).code;

describe("registration", () => {
  it("issues a token the Worker accepts, and limits how many one network can take in a day", async () => {
    const responses = [];
    for (let attempt = 0; attempt <= REGISTRATIONS_PER_NETWORK; attempt += 1) responses.push(await register("203.0.113.1"));
    const { token } = (await responses[0].json()) as { token: string };
    expect(responses.slice(0, -1).map((response) => response.status)).toEqual(Array(REGISTRATIONS_PER_NETWORK).fill(201));
    expect((await upload(token, "203.0.113.1", frameId(1))).status).toBe(201);

    const refused = responses.at(-1)!;
    expect(refused.status).toBe(429);
    expect(Number(refused.headers.get("Retry-After"))).toBeGreaterThan(0);
    const body = (await refused.json()) as { code: string; retry_at: number };
    expect(body.code).toBe("network_daily");
    expect(body.retry_at * 1000).toBeGreaterThan(Date.now());
    expect((await register("203.0.113.2")).status).toBe(201);
  });

  it("counts an IPv6 network by its /48, the most one site is routed", () => {
    expect(networkOf("2001:db8:1:2:aaaa:bbbb:cccc:dddd")).toBe(networkOf("2001:db8:1:ffff::1"));
    expect(networkOf("2001:db8:1::")).toBe(networkOf("2001:db8:1:2::1"));
    expect(networkOf("2001:db8:2:2::1")).not.toBe(networkOf("2001:db8:1:2::1"));
    expect(networkOf("198.51.100.7")).toBe("198.51.100.7");
  });

  it("turns away a request a web page could send from a visitor's browser, without counting it", async () => {
    const fromAPage = [
      await register("203.0.113.3", { "Content-Type": "text/plain" }),
      await register("203.0.113.3", { "Content-Type": "application/json", Origin: "https://elsewhere.example" }),
    ];
    for (let attempt = 0; attempt < REGISTRATIONS_PER_NETWORK; attempt += 1) fromAPage.push(await register("203.0.113.3", { "Content-Type": "text/plain" }));
    expect(fromAPage.map((response) => response.status)).toEqual(Array(fromAPage.length).fill(403));
    expect(await code(fromAPage[0])).toBe("browser");
    expect((await register("203.0.113.3")).status).toBe(201);
  });
});

describe("uploading a frame", () => {
  it("stores the JPEG under the hub and print with its labels", async () => {
    const token = await issueToken(env.TOKEN_SECRET);
    const response = await upload(token, "203.0.113.10", frameId(2), JPEG, { label: "failure", kind: "alert", printer: "Prusa MK4" });
    expect(response.status).toBe(201);

    const stored = await env.FRAMES.get(`${token.split(".")[0]}/aaaaaaaaaaaa/${frameId(2)}.jpg`);
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(JPEG);
    expect(stored!.httpMetadata?.contentType).toBe("image/jpeg");
    expect(stored!.customMetadata).toMatchObject({ label: "failure", kind: "alert", score: "0.12", printer: "Prusa MK4", version: "2.6.0" });
  });

  it("turns away a made-up token, an oversized body, a file that is not a JPEG and unknown labels", async () => {
    const token = await issueToken(env.TOKEN_SECRET);
    const forged = `${"0".repeat(32)}.${"0".repeat(64)}`;
    const refusals = [
      await upload(forged, "203.0.113.11", frameId(3)),
      await upload("nonsense", "203.0.113.11", frameId(3)),
      await upload(token, "203.0.113.11", frameId(3), new Uint8Array(FRAME_BYTES_MAX + 1).fill(0xff)),
      await upload(token, "203.0.113.11", frameId(3), new Uint8Array([0x89, 0x50, 0x4e, 0x47])),
      await upload(token, "203.0.113.11", frameId(3), JPEG, { label: "maybe" }),
      await upload(token, "203.0.113.11", "../escape", JPEG),
    ];
    expect(refusals.map((response) => response.status)).toEqual([401, 401, 413, 415, 400, 400]);
    expect(await Promise.all(refusals.map(code))).toEqual(["token", "token", "too_large", "not_jpeg", "details", "details"]);
    expect((await env.FRAMES.list({ prefix: token.split(".")[0] })).objects).toEqual([]);
  });

  it("stops one hub at its daily limit and leaves other hubs alone", async () => {
    const token = await issueToken(env.TOKEN_SECRET);
    for (let sent = 0; sent < UPLOADS_PER_HUB; sent += 1) {
      expect((await upload(token, "203.0.113.12", frameId(100 + sent))).status).toBe(201);
    }
    const refused = await upload(token, "203.0.113.12", frameId(999));
    expect(refused.status).toBe(429);
    expect(await code(refused)).toBe("hub_daily");
    expect((await upload(await issueToken(env.TOKEN_SECRET), "203.0.113.12", frameId(1000))).status).toBe(201);
  });

  it("counts a frame sent twice once", async () => {
    const token = await issueToken(env.TOKEN_SECRET);
    const gate = env.GATE.getByName("gate");
    await upload(token, "203.0.113.13", frameId(2000));
    const afterFirst = await gate.storedBytes();
    expect((await upload(token, "203.0.113.13", frameId(2000))).status).toBe(201);
    expect(await gate.storedBytes()).toBe(afterFirst);
    await upload(token, "203.0.113.13", frameId(2000), new Uint8Array([...JPEG, 5, 6]));
    expect(await gate.storedBytes()).toBe(afterFirst + 2);
  });

  it("answers closed when collection is switched off", async () => {
    const response = await worker.fetch(new Request(`${ORIGIN}/register`, { method: "POST" }), { ...env, ACCEPTING: "false" });
    expect(response.status).toBe(503);
    expect(await code(response)).toBe("closed");
  });
});

describe("the gate", () => {
  it("stops one network at its daily limit however many hubs it uses", async () => {
    const gate = env.GATE.getByName("network-limit");
    for (let sent = 0; sent < UPLOADS_PER_NETWORK; sent += 1) expect(await gate.reserve(`hub-${sent}`, "198.51.100.1", 10)).toBeNull();
    expect(await gate.reserve("another-hub", "198.51.100.1", 10)).toMatchObject({ status: 429, code: "network_daily" });
    expect(await gate.reserve("another-hub", "198.51.100.2", 10)).toBeNull();
  });

  it("stops everyone at the global daily limit", async () => {
    const gate = env.GATE.getByName("global-limit");
    for (let sent = 0; sent < UPLOADS_PER_DAY; sent += 1) expect(await gate.reserve(`hub-${sent}`, `network-${sent}`, 10)).toBeNull();
    expect(await gate.reserve("late-hub", "late-network", 10)).toMatchObject({ status: 429, code: "global_daily" });
  });

  it("never lets the stored bytes pass the cap, and frees room when a write is released or the bucket is recounted", async () => {
    const gate = env.GATE.getByName("storage-cap");
    await gate.recount(STORED_BYTES_MAX - 100);
    expect(await gate.reserve("hub", "network", 100)).toBeNull();
    expect(await gate.storedBytes()).toBe(STORED_BYTES_MAX);
    expect(await gate.reserve("hub", "network", 1)).toEqual({ status: 507, code: "storage_full" });

    await gate.release("hub", "network", 100);
    expect(await gate.reserve("hub", "network", 100)).toBeNull();
    await gate.recount(0);
    expect(await gate.reserve("hub", "network", FRAME_BYTES_MAX)).toBeNull();
  });
});

describe("the daily recount", () => {
  it("resets the stored total to what is really in the bucket", async () => {
    const token = await issueToken(env.TOKEN_SECRET);
    await upload(token, "203.0.113.20", frameId(5000));
    const before = await env.GATE.getByName("gate").storedBytes();
    await env.FRAMES.delete(`${token.split(".")[0]}/aaaaaaaaaaaa/${frameId(5000)}.jpg`);

    await worker.scheduled(createScheduledController(), env);

    const inBucket = (await env.FRAMES.list()).objects.reduce((bytes, object) => bytes + object.size, 0);
    expect(await env.GATE.getByName("gate").storedBytes()).toBe(inBucket);
    expect(inBucket).toBe(before - JPEG.byteLength);
  });

  it("keeps the bytes that arrive while the bucket is being listed", async () => {
    const gate = env.GATE.getByName("recount-race");
    await gate.reserve("hub", "network", 300);
    await gate.beginRecount();
    await gate.reserve("hub", "network", 50);
    await gate.recount(300);
    expect(await gate.storedBytes()).toBe(350);

    await gate.beginRecount();
    await gate.recount(350);
    expect(await gate.storedBytes()).toBe(350);
  });

  it("counts a frame as expiring once it is within the warning of the expiry", () => {
    const now = Date.UTC(2026, 9, 31);
    const uploadedDaysAgo = (days: number) => new Date(now - days * DAY_MS);
    expect(expiresSoon(uploadedDaysAgo(EXPIRY_DAYS - EXPIRY_WARN_DAYS), now)).toBe(true);
    expect(expiresSoon(uploadedDaysAgo(EXPIRY_DAYS - EXPIRY_WARN_DAYS - 1), now)).toBe(false);
    expect(expiresSoon(uploadedDaysAgo(EXPIRY_DAYS), now)).toBe(true);
  });

  it("reminds me when frames are close to expiring or the inbox is nearly full", () => {
    expect(reminders({ bytes: 1024, expiring: 0 })).toEqual([]);
    expect(reminders({ bytes: 1024, expiring: 312 })).toEqual(["312 frames expire within 7 days."]);
    expect(reminders({ bytes: STORED_BYTES_WARN, expiring: 0 })).toEqual(["The inbox is 80% full."]);
  });
});
