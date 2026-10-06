import { DurableObject } from "cloudflare:workers";
import {
  DAY_MS,
  REGISTRATIONS_PER_NETWORK,
  STORED_BYTES_MAX,
  UPLOADS_PER_DAY,
  UPLOADS_PER_HUB,
  UPLOADS_PER_NETWORK,
} from "./limits";

export type Refusal = { status: number; code: string; retryAt?: number };
export type Reservation = { bytes: number; uploads: number };

const STORED_BYTES = "stored_bytes";
const BYTES_SINCE_RECOUNT_BEGAN = "bytes_since_recount_began";
const RECOUNT_BEGAN_AT = "recount_began_at";

const today = () => new Date().toISOString().slice(0, 10);

const untilTomorrow = (code: string): Refusal => ({
  status: 429,
  code,
  retryAt: (Math.floor(Date.now() / DAY_MS) + 1) * (DAY_MS / 1000),
});

export class Gate extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS counts (day TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, scope, key))",
      );
    });
  }

  register(network: string): Refusal | null {
    if (this.count("registrations", network) >= REGISTRATIONS_PER_NETWORK) return untilTomorrow("network_daily");
    this.add("registrations", network, 1);
    return null;
  }

  reserve(hub: string, network: string, frame: string, bytes: number): Refusal | Reservation {
    if (this.count("frame", frame) > 0) return { bytes: 0, uploads: 0 };
    if (this.count("hub", hub) >= UPLOADS_PER_HUB) return untilTomorrow("hub_daily");
    if (this.count("network", network) >= UPLOADS_PER_NETWORK) return untilTomorrow("network_daily");
    if (this.count("everyone", "") >= UPLOADS_PER_DAY) return untilTomorrow("global_daily");
    if (this.storedBytes() + bytes > STORED_BYTES_MAX) return { status: 507, code: "storage_full" };
    this.tally(hub, network, bytes, 1);
    this.add("frame", frame, bytes);
    return { bytes, uploads: 1 };
  }

  release(hub: string, network: string, frame: string, reservation: Reservation): void {
    if (reservation.uploads === 0 || this.count("stored", frame) > 0) return;
    this.tally(hub, network, -reservation.bytes, -reservation.uploads);
    this.add("frame", frame, -reservation.bytes);
  }

  stored(hub: string, network: string, frame: string, bytes: number): void {
    if (this.count("frame", frame) === 0) {
      this.tally(hub, network, bytes, 1);
      this.add("frame", frame, bytes);
    }
    this.add("stored", frame, 1);
  }

  beginRecount(minimumGapMs: number): boolean {
    if (Date.now() - (this.ctx.storage.kv.get<number>(RECOUNT_BEGAN_AT) ?? 0) < minimumGapMs) return false;
    this.ctx.storage.kv.put(RECOUNT_BEGAN_AT, Date.now());
    this.ctx.storage.kv.put(BYTES_SINCE_RECOUNT_BEGAN, 0);
    this.ctx.storage.sql.exec("DELETE FROM counts WHERE day < ?", today());
    return true;
  }

  recount(listedBytes: number): void {
    this.ctx.storage.kv.put(STORED_BYTES, listedBytes + this.bytesSinceRecountBegan());
  }

  storedBytes(): number {
    return this.ctx.storage.kv.get<number>(STORED_BYTES) ?? 0;
  }

  private bytesSinceRecountBegan(): number {
    return this.ctx.storage.kv.get<number>(BYTES_SINCE_RECOUNT_BEGAN) ?? 0;
  }

  private tally(hub: string, network: string, bytes: number, uploads: number): void {
    this.ctx.storage.kv.put(STORED_BYTES, this.storedBytes() + bytes);
    this.ctx.storage.kv.put(BYTES_SINCE_RECOUNT_BEGAN, this.bytesSinceRecountBegan() + bytes);
    this.add("hub", hub, uploads);
    this.add("network", network, uploads);
    this.add("everyone", "", uploads);
  }

  private count(scope: string, key: string): number {
    const rows = this.ctx.storage.sql
      .exec<{ n: number }>("SELECT n FROM counts WHERE day = ? AND scope = ? AND key = ?", today(), scope, key)
      .toArray();
    return rows[0]?.n ?? 0;
  }

  private add(scope: string, key: string, by: number): void {
    this.ctx.storage.sql.exec(
      "INSERT INTO counts (day, scope, key, n) VALUES (?, ?, ?, ?) ON CONFLICT (day, scope, key) DO UPDATE SET n = n + excluded.n",
      today(),
      scope,
      key,
      by,
    );
  }
}
