import { useEffect, useId, useMemo, useState } from "react";
import { groupBuckets, PERIODS, type Period } from "../history";
import { useStore } from "../store";
import type { Monitor, Snapshot } from "../types";
import { Modal } from "./Dialog";
import { DefectBars, RiskBandChart } from "./RiskChart";
import { riskColor, RiskGauge } from "./RiskGauge";

const HISTORY_POLL_MS = 5000;

function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function duration(min: number): string {
  if (min < 60) return `${min}m`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-3 py-2">
      <div className="mono text-base text-text-0">{value}</div>
      <div className="label mt-0.5">{label}</div>
    </div>
  );
}

function SnapshotThumb({ monitorId, snap, threshold, onOpen }: { monitorId: string; snap: Snapshot; threshold: number; onOpen: () => void }) {
  const url = useStore((s) => s.snapshotCache[snap.id]);
  const fetchSnapshot = useStore((s) => s.fetchSnapshot);
  useEffect(() => {
    fetchSnapshot(monitorId, snap.id);
  }, [monitorId, snap.id]);
  return (
    <button type="button" onClick={onOpen} className="panel group relative block overflow-hidden text-left" aria-label={`Snapshot at ${(snap.score * 100).toFixed(0)}% risk, ${ago(snap.ts)}`}>
      <div className="aspect-video bg-ink-0">
        {url ? (
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center">
            <span className="mono text-[0.6rem] tracking-[0.2em] text-text-2 uppercase">loading</span>
          </div>
        )}
      </div>
      <span className="chip absolute right-1 top-1" style={{ color: riskColor(snap.score, threshold), borderColor: riskColor(snap.score, threshold) }}>
        {(snap.score * 100).toFixed(0)}%
      </span>
      <span className="label absolute inset-x-0 bottom-0 bg-ink-1/85 px-2 py-1">
        {ago(snap.ts)}
        {snap.action !== "none" && ` · ${snap.action}`}
      </span>
    </button>
  );
}

export function StatsPage({ monitor }: { monitor: Monitor }) {
  const { historyData, openStats, send } = useStore();
  const titleId = useId();
  const [period, setPeriod] = useState<Period>("1h");
  const [sortByScore, setSortByScore] = useState(false);
  const [enlarged, setEnlarged] = useState<Snapshot | null>(null);
  const enlargedUrl = useStore((s) => (enlarged ? s.snapshotCache[enlarged.id] : undefined));
  const history = historyData[monitor.id];
  const close = () => openStats(null);

  useEffect(() => {
    const timer = setInterval(() => send({ cmd: "history.get", monitor_id: monitor.id }), HISTORY_POLL_MS);
    return () => clearInterval(timer);
  }, [monitor.id]);

  const grouped = useMemo(() => groupBuckets(history?.buckets ?? [], period, Date.now() / 1000), [history, period]);
  const stats = history?.stats ?? {};
  const snaps = useMemo(
    () => [...(history?.snaps ?? [])].sort((a, b) => (sortByScore ? b.score - a.score : b.ts - a.ts)),
    [history, sortByScore],
  );
  const pct = (v: number | undefined) => `${((v ?? 0) * 100).toFixed(0)}%`;

  return (
    <Modal onClose={close} variant="sheet" labelledBy={titleId}>
      <aside className="slide-in h-full w-full sm:w-[680px] bg-ink-1 border-l border-line-0 overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-center gap-2.5 px-5 py-3.5 border-b border-line-0 bg-ink-1/95 backdrop-blur-sm">
          <h2 id={titleId} className="display text-lg font-semibold flex-1 truncate">
            {monitor.name} · history
          </h2>
          <button type="button" className="text-text-2 hover:text-accent text-2xl leading-none cursor-pointer" onClick={close} aria-label="Close detailed history">
            ×
          </button>
        </div>

        <div className="px-5 py-4 border-b border-line-0">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="row-span-2 flex items-center justify-center">
              <RiskGauge score={stats.current ?? 0} threshold={monitor.threshold} size={92} />
            </div>
            <StatTile label="average" value={pct(stats.avg)} />
            <StatTile label="peak" value={pct(stats.max)} />
            <StatTile label="defect rate" value={`${(stats.defect_pct ?? 0).toFixed(0)}%`} />
            <StatTile label="frames" value={String(stats.inferences ?? 0)} />
            <StatTile label="alerts" value={String(stats.alerts ?? 0)} />
            <StatTile label="watch time" value={duration(stats.watch_min ?? 0)} />
          </div>
        </div>

        <div className="px-5 py-4 border-b border-line-0">
          <div className="mb-3 flex items-center gap-2">
            <h3 className="display text-[0.68rem] font-semibold tracking-[0.24em] text-text-2 flex-1">RISK PER PERIOD</h3>
            {PERIODS.map((p) => (
              <button
                key={p}
                className={`btn !py-1 !px-2 !text-[0.6rem] ${period === p ? "!border-accent !text-accent" : ""}`}
                aria-pressed={period === p}
                onClick={() => setPeriod(p)}
              >
                {p}
              </button>
            ))}
          </div>
          {grouped.length === 0 ? (
            <p className="mono text-[0.7rem] text-text-2 py-8 text-center">awaiting results</p>
          ) : (
            <>
              <RiskBandChart data={grouped} threshold={monitor.threshold} />
              <DefectBars data={grouped} />
              <div className="mt-1 flex justify-between">
                <span className="label">{clock(grouped[0].t)}</span>
                <span className="label">{clock(grouped[grouped.length - 1].t)}</span>
              </div>
            </>
          )}
        </div>

        <div className="px-5 py-4">
          <div className="mb-3 flex items-center gap-2">
            <h3 className="display text-[0.68rem] font-semibold tracking-[0.24em] text-text-2 flex-1">RISKY MOMENTS</h3>
            {snaps.length > 0 && (
              <button className="btn !py-1 !px-2 !text-[0.6rem]" onClick={() => setSortByScore((v) => !v)}>
                {sortByScore ? "by time" : "by risk"}
              </button>
            )}
          </div>
          {snaps.length === 0 ? (
            <p className="mono text-[0.7rem] text-text-2">No alerts have fired yet — a snapshot is captured each time a defect alert triggers.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {snaps.map((snap) => (
                <SnapshotThumb key={snap.id} monitorId={monitor.id} snap={snap} threshold={monitor.threshold} onOpen={() => setEnlarged(snap)} />
              ))}
            </div>
          )}
        </div>

        {enlarged && (
          <button
            type="button"
            className="fixed inset-0 z-20 grid place-items-center bg-ink-0/90 p-6"
            onClick={() => setEnlarged(null)}
            aria-label="Close snapshot"
          >
            {enlargedUrl && <img src={enlargedUrl} alt="" className="max-h-full max-w-full object-contain" />}
            <span className="mono absolute left-6 top-6 text-sm" style={{ color: riskColor(enlarged.score, monitor.threshold) }}>
              {(enlarged.score * 100).toFixed(0)}% · {ago(enlarged.ts)}
              {enlarged.action !== "none" && ` · ${enlarged.action}`}
            </span>
          </button>
        )}
      </aside>
    </Modal>
  );
}
