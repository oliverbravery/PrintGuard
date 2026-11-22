import { useEffect, useMemo, useState } from "react";
import { Navigate, useParams } from "react-router";
import { alertOutcome, GROUP_S, groupBuckets, HISTORY_BUCKET_MS, PERIODS, type Period } from "../history";
import { clock } from "../review";
import { useLazySnapshot } from "../snapshot";
import { useStore } from "../store";
import type { Snapshot } from "../types";
import { Page } from "./Page";
import { ReviewList } from "./ReviewList";
import { RiskPeriodChart } from "./RiskChart";
import { riskColor, RiskMeter } from "./RiskMeter";
import { SnapshotLightbox } from "./SnapshotLightbox";

function ago(ts: number, now: number): string {
  const s = Math.max(0, now - ts);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function duration(min: number): string {
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-l border-line-0 px-4 py-3">
      <div className="label">{label}</div>
      <div className="mono text-xl font-semibold tracking-[-0.02em]">{value}</div>
    </div>
  );
}

function SnapshotThumb({ monitorId, snap, threshold, now, onOpen }: { monitorId: string; snap: Snapshot; threshold: number; now: number; onOpen: () => void }) {
  const { ref, url } = useLazySnapshot<HTMLButtonElement>(monitorId, snap.id);
  return (
    <button
      ref={ref}
      type="button"
      onClick={onOpen}
      className="group relative block overflow-hidden border-b border-r border-line-0 text-left hover:bg-ink-1"
      aria-label={`Snapshot at ${(snap.score * 100).toFixed(0)}% risk, ${ago(snap.ts, now)}`}
    >
      <div className="aspect-video bg-ink-1">
        {url ? (
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center">
            <span className="mono text-xs uppercase tracking-[0.12em] text-text-2">loading</span>
          </div>
        )}
      </div>
      <span className="mono flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
        <span className="text-text-1">
          {ago(snap.ts, now)}
          {alertOutcome(snap.action) && ` · ${alertOutcome(snap.action)}`}
        </span>
        <span className="font-semibold" style={{ color: riskColor(snap.score, threshold) }}>
          {(snap.score * 100).toFixed(0)}%
        </span>
      </span>
    </button>
  );
}

function SectionHead({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-h-11 items-center gap-2 border-b border-rule bg-ink-1 px-4 py-1.5">
      <h2 className="label flex-1 text-text-1">{title}</h2>
      {children}
    </div>
  );
}

export function HistoryPage() {
  const { monitorId } = useParams();
  const { engine, historyData, history: scores, reconnecting, fetchHistory } = useStore();
  const monitor = engine?.monitors.find((m) => m.id === monitorId);
  const camera = engine?.cameras.find((c) => c.id === monitor?.camera_id);
  const reviews = (engine?.reviews ?? []).filter((review) => review.monitor_id === monitorId);
  const alertsKept = reviews.reduce((kept, review) => kept + review.alerts, 0);
  const [period, setPeriod] = useState<Period>("1h");
  const [sortByScore, setSortByScore] = useState(false);
  const [enlarged, setEnlarged] = useState<Snapshot | null>(null);
  const history = monitorId ? historyData[monitorId] : undefined;

  useEffect(() => {
    if (reconnecting || !monitorId) return;
    fetchHistory(monitorId);
    const refresh = setInterval(() => fetchHistory(monitorId), HISTORY_BUCKET_MS);
    return () => clearInterval(refresh);
  }, [monitorId, reconnecting, alertsKept]);

  const grouped = useMemo(() => (history ? groupBuckets(history.buckets, period, history.now) : []), [history, period]);
  const snaps = useMemo(
    () => [...(history?.snaps ?? [])].sort((a, b) => (sortByScore ? b.score - a.score : b.ts - a.ts)),
    [history, sortByScore],
  );
  if (!monitor) return <Navigate to="/" replace />;
  const day = (ts: number) => new Date(ts * 1000).toDateString();
  const withinOneDay = grouped.length > 0 && day(grouped[0].t) === day(grouped[grouped.length - 1].t);
  const axisTime = (ts: number) =>
    withinOneDay ? clock(ts) : new Date(ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const stats = history?.stats ?? {};
  const pct = (v: number | undefined) => `${((v ?? 0) * 100).toFixed(0)}%`;
  const live = camera?.online && monitor.watching ? (scores[monitor.id]?.at(-1)?.score ?? stats.current ?? 0) : null;

  return (
    <Page title={`${monitor.name} history`} back={{ to: `/monitors/${monitor.id}`, label: "Monitors" }} subview>
      <div className="grid border-b border-rule md:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <div className="border-b border-line-0 px-4 py-4 md:border-b-0 md:border-r">
          <div className="label mb-2">Risk now</div>
          <RiskMeter score={live} threshold={monitor.threshold} size="hero" />
        </div>
        <div className="-ml-px grid grid-cols-2 sm:grid-cols-3">
          <StatTile label="average" value={pct(stats.avg)} />
          <StatTile label="peak" value={pct(stats.max)} />
          <StatTile label="defect rate" value={`${(stats.defect_pct ?? 0).toFixed(0)}%`} />
          <StatTile label="frames" value={String(stats.inferences ?? 0)} />
          <StatTile label="alerts" value={String(Math.max(stats.alerts ?? 0, snaps.length))} />
          <StatTile label="watch time" value={duration(stats.watch_min ?? 0)} />
        </div>
      </div>

      <section className="border-b border-rule">
        <SectionHead title="Risk per period">
          {PERIODS.map((p) => (
            <button key={p} className="btn-inline" aria-pressed={period === p} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
        </SectionHead>
        <div className="px-4 py-4">
          {grouped.length === 0 ? (
            <p className="mono py-8 text-center text-xs text-text-2">{history ? "awaiting results" : "loading history"}</p>
          ) : (
            <RiskPeriodChart data={grouped} span={GROUP_S[period]} threshold={monitor.threshold} time={axisTime} />
          )}
        </div>
      </section>

      <div className="grid lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <section className="border-b border-rule lg:border-r">
          <SectionHead title="Prints" />
          <ReviewList monitorId={monitor.id} />
        </section>
        <section className="border-b border-rule">
          <SectionHead title="Risky moments">
            {snaps.length > 0 && (
              <button className="btn-inline" onClick={() => setSortByScore((v) => !v)}>
                {sortByScore ? "by time" : "by risk"}
              </button>
            )}
          </SectionHead>
          {snaps.length === 0 ? (
            <p className="px-4 py-4 text-sm text-text-2">
              {history ? "No alerts have fired yet. A snapshot is captured each time a defect alert triggers." : "loading history"}
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4">
              {history &&
                snaps.map((snap) => (
                  <SnapshotThumb key={snap.id} monitorId={monitor.id} snap={snap} threshold={monitor.threshold} now={history.now} onOpen={() => setEnlarged(snap)} />
                ))}
            </div>
          )}
        </section>
      </div>

      {enlarged && (
        <SnapshotLightbox
          snapshotId={enlarged.id}
          color={riskColor(enlarged.score, monitor.threshold)}
          onClose={() => setEnlarged(null)}
          caption={
            <>
              {(enlarged.score * 100).toFixed(0)}% · {history && ago(enlarged.ts, history.now)}
              {alertOutcome(enlarged.action) && ` · ${alertOutcome(enlarged.action)}`}
            </>
          }
        />
      )}
    </Page>
  );
}
