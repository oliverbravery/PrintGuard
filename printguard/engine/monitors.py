"""Monitor configuration, covering defaults, validation, watch-state and serialisation.

A monitor binds a camera and, optionally, a registered printer, and carries the
inference thresholds and defect-response policy for that pairing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .bounds import clamp

if TYPE_CHECKING:
    from .registry import PrinterRegistry

MONITOR_DEFAULTS: dict[str, Any] = {
    "name": "Monitor",
    "camera_id": "",
    "printer_id": "",
    "enabled": True,
    "threshold": 0.75,
    "consecutive": 3,
    "notify": False,
    "on_defect": "none",
    "cooldown_s": 60,
}

STANDBY_STATUSES = ("idle", "paused", "error")

# A score only approaches 1, and of the failure frames the model was trained
# on one in seven passes 0.95 and one in seventy 0.99, so a threshold above
# this would switch a monitor off without saying so.
THRESHOLD_MAX = 0.95

_CLAMPS = {"threshold": (0.05, THRESHOLD_MAX), "consecutive": (1, 30), "cooldown_s": (0, 600)}


def monitor_watching(monitor: dict[str, Any], printers: "PrinterRegistry") -> bool:
    """Whether monitoring should run for a monitor right now.

    A monitor is watched unless its linked printer last positively reported a
    non-printing state. An unreachable printer or a state the adapter cannot
    read keeps that last answer, so contact lost mid-print keeps watching
    while a printer switched off after a print stays in standby. With no
    printer linked or nothing read yet the monitor is watched - failing
    towards watching is the safe direction.
    """
    if not monitor.get("enabled"):
        return False
    printer = printers.get(monitor.get("printer_id") or "")
    return printer is None or printer.reported_status not in STANDBY_STATUSES


def sanitise_monitor(monitor_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a monitor patch over defaults or an existing record.

    Args:
        monitor_id: Stable identifier for the monitor.
        patch: Partial monitor fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated monitor record.

    Raises:
        ValueError: If the threshold, streak or cooldown is not a finite number.
    """
    record = {**(base or MONITOR_DEFAULTS), **patch, "id": monitor_id}
    record["name"] = str(record["name"]).strip() or "Monitor"
    record["camera_id"] = str(record["camera_id"] or "")
    record["printer_id"] = str(record["printer_id"] or "")
    record["threshold"] = clamp("threshold", record["threshold"], *_CLAMPS["threshold"])
    record["consecutive"] = int(clamp("consecutive", record["consecutive"], *_CLAMPS["consecutive"]))
    record["cooldown_s"] = int(clamp("cooldown_s", record["cooldown_s"], *_CLAMPS["cooldown_s"]))
    record["enabled"] = bool(record["enabled"])
    record["notify"] = bool(record["notify"])
    if record["on_defect"] not in ("none", "pause", "cancel"):
        record["on_defect"] = "none"
    return record


def persisted_monitor(record: dict[str, Any]) -> dict[str, Any]:
    """Keeps only a monitor's configuration, dropping runtime and retired fields."""
    return {k: record[k] for k in ("id", *MONITOR_DEFAULTS)}
