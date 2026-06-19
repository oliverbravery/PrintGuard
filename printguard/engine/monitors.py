"""Monitor configuration: defaults, validation, watch-state and serialisation.

A monitor binds a camera and, optionally, a registered printer, and carries the
inference thresholds and defect-response policy for that pairing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import PrinterRegistry

MONITOR_DEFAULTS: dict[str, Any] = {
    "name": "Monitor",
    "camera_id": "",
    "printer_id": "",
    "enabled": True,
    "threshold": 0.75,
    "sensitivity": 1.0,
    "consecutive": 3,
    "notify": False,
    "on_defect": "none",
    "cooldown_s": 60,
}

STANDBY_STATUSES = ("idle", "paused", "error")

_CLAMPS = {"threshold": (0.05, 1.0), "sensitivity": (0.2, 5.0), "consecutive": (1, 30), "cooldown_s": (0, 600)}


def monitor_watching(monitor: dict[str, Any], printers: "PrinterRegistry") -> bool:
    """Whether monitoring should run for a monitor right now.

    A monitor is watched unless its linked printer positively reports a
    non-printing state. With no printer linked, no state polled yet, or an
    unreachable printer the monitor stays watched — failing towards watching
    is the safe direction.
    """
    if not monitor.get("enabled"):
        return False
    printer = printers.get(monitor.get("printer_id") or "")
    if printer is None:
        return True
    state = printer.device_state
    return not state or state["status"] not in STANDBY_STATUSES


def _clamp(key: str, value: float) -> float:
    low, high = _CLAMPS[key]
    return max(low, min(high, value))


def sanitise_monitor(monitor_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a monitor patch over defaults or an existing record.

    Args:
        monitor_id: Stable identifier for the monitor.
        patch: Partial monitor fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated monitor record.
    """
    record = {**(base or MONITOR_DEFAULTS), **patch, "id": monitor_id}
    record["name"] = str(record["name"]).strip() or "Monitor"
    record["threshold"] = _clamp("threshold", float(record["threshold"]))
    record["sensitivity"] = _clamp("sensitivity", float(record["sensitivity"]))
    record["consecutive"] = int(_clamp("consecutive", int(record["consecutive"])))
    record["cooldown_s"] = int(_clamp("cooldown_s", int(record["cooldown_s"])))
    record["enabled"] = bool(record["enabled"])
    record["notify"] = bool(record["notify"])
    if record["on_defect"] not in ("none", "pause", "cancel"):
        record["on_defect"] = "none"
    return record


def persisted_monitor(record: dict[str, Any]) -> dict[str, Any]:
    """Strips runtime-only fields before persistence."""
    return {k: v for k, v in record.items() if k not in ("alert", "watching")}
