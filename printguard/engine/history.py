"""Per-monitor risk history, rolled-up time buckets and the alert log.

Each inference score is folded into a fixed-interval rollup bucket (count, sum,
min, max and a defect tally) and every fired alert is logged. Both series are
bounded in-memory rings, read on demand by the detailed monitor view over the
engine protocol. The frames that fired the alerts are kept by the review
library.
"""

from __future__ import annotations

from collections import deque
from typing import Any

BUCKET_S = 60
BUCKET_CAP = 1440
ALERT_CAP = 50


class MonitorHistory:
    """Bounded rollup buckets and the alert log for one monitor."""

    def __init__(self) -> None:
        self.buckets: deque[dict[str, Any]] = deque(maxlen=BUCKET_CAP)
        self.alerts: deque[dict[str, Any]] = deque(maxlen=ALERT_CAP)
        self._last_score = 0.0

    def record(self, ts: float, score: float, threshold: float) -> None:
        """Folds one inference score into its fixed-interval bucket."""
        self._last_score = score
        start = int(ts // BUCKET_S) * BUCKET_S
        bucket = self.buckets[-1] if self.buckets else None
        if bucket is None or bucket["t"] != start:
            bucket = {"t": start, "n": 0, "sum": 0.0, "min": score, "max": score, "defects": 0}
            self.buckets.append(bucket)
        bucket["n"] += 1
        bucket["sum"] += score
        bucket["min"] = min(bucket["min"], score)
        bucket["max"] = max(bucket["max"], score)
        if score >= threshold:
            bucket["defects"] += 1

    def record_alert(self, ts: float, score: float, action: str) -> None:
        """Logs a fired alert."""
        self.alerts.append({"ts": ts, "score": score, "action": action})

    def series(self, snaps: list[dict[str, Any]]) -> dict[str, Any]:
        """Builds the buckets, snapshot index, alert log and summary statistics.

        Args:
            snaps: The kept alert frames of the monitor, oldest first.
        """
        buckets = [{k: v for k, v in b.items()} for b in self.buckets]
        inferences = sum(b["n"] for b in buckets)
        defect_frames = sum(b["defects"] for b in buckets)
        total = sum(b["sum"] for b in buckets)
        stats = {
            "current": round(self._last_score, 4),
            "avg": round(total / inferences, 4) if inferences else 0.0,
            "min": round(min((b["min"] for b in buckets), default=0.0), 4),
            "max": round(max((b["max"] for b in buckets), default=0.0), 4),
            "inferences": inferences,
            "defect_frames": defect_frames,
            "defect_pct": round(100.0 * defect_frames / inferences, 1) if inferences else 0.0,
            "alerts": len(self.alerts),
            "watch_min": sum(1 for b in buckets if b["n"] > 0),
            "snaps": len(snaps),
        }
        return {
            "buckets": buckets,
            "snaps": [{"id": s["id"], "ts": s["ts"], "score": s["score"], "action": s["action"]} for s in snaps],
            "alerts": list(self.alerts),
            "stats": stats,
        }
