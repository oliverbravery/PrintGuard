"""Per-monitor risk history: rolled-up time buckets and alert snapshots.

Each inference score is folded into a fixed-interval rollup bucket (count, sum,
min, max and a defect tally); every fired alert is logged and keeps the JPEG of
the frame that triggered it. Both series are bounded in-memory rings, read on
demand by the detailed monitor view over the engine protocol; nothing here is
platform specific.
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Any

BUCKET_S = 60
BUCKET_CAP = 1440
SNAP_CAP = 40
ALERT_CAP = 50


class MonitorHistory:
    """Bounded rollup buckets and alert snapshots for one monitor."""

    def __init__(self) -> None:
        self.buckets: deque[dict[str, Any]] = deque(maxlen=BUCKET_CAP)
        self.snaps: deque[dict[str, Any]] = deque(maxlen=SNAP_CAP)
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

    def record_alert(self, ts: float, score: float, action: str, jpeg: bytes | None) -> None:
        """Logs a fired alert and keeps its triggering frame as a snapshot."""
        self.alerts.append({"ts": ts, "score": score, "action": action})
        if jpeg:
            self.snaps.append({"id": uuid.uuid4().hex[:12], "ts": ts, "score": score, "action": action, "jpeg": jpeg})

    def snapshot(self, snap_id: str) -> bytes | None:
        """Returns the stored JPEG bytes for a snapshot id, or None."""
        for snap in self.snaps:
            if snap["id"] == snap_id:
                return snap["jpeg"]
        return None

    def series(self) -> dict[str, Any]:
        """Builds the buckets, snapshot index, alert log and summary statistics."""
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
            "snaps": len(self.snaps),
        }
        return {
            "buckets": buckets,
            "snaps": [{"id": s["id"], "ts": s["ts"], "score": s["score"], "action": s["action"]} for s in self.snaps],
            "alerts": list(self.alerts),
            "stats": stats,
        }
