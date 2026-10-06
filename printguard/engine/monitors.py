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
ON_DEFECT = ("none", "pause", "cancel")

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
        ValueError: If the patch names a setting a monitor does not have, the
            threshold, streak or cooldown is not a finite number, or another
            value is not of the kind its setting takes.
    """
    unknown = sorted(set(patch) - set(MONITOR_DEFAULTS))
    if unknown:
        raise ValueError(f"a monitor has no {unknown[0]} setting")
    record = {**(base or MONITOR_DEFAULTS), **patch, "id": monitor_id}
    for key in ("name", "camera_id", "printer_id"):
        if not isinstance(record[key], str):
            raise ValueError(f"a monitor's {key} is text")
    for key in ("enabled", "notify"):
        if not isinstance(record[key], bool):
            raise ValueError(f"a monitor's {key} is true or false")
    if record["on_defect"] not in ON_DEFECT:
        raise ValueError(f"on_defect is one of {', '.join(ON_DEFECT)}")
    record["name"] = record["name"].strip() or "Monitor"
    record["threshold"] = clamp("threshold", record["threshold"], *_CLAMPS["threshold"])
    record["consecutive"] = int(clamp("consecutive", record["consecutive"], *_CLAMPS["consecutive"]))
    record["cooldown_s"] = int(clamp("cooldown_s", record["cooldown_s"], *_CLAMPS["cooldown_s"]))
    return record


def stored_monitor(record: dict[str, Any]) -> dict[str, Any]:
    """Reads a monitor back from the state store, leaving out a setting a later version retired.

    A monitor with no printer, which an earlier version stored as null, has an
    empty printer id.

    Raises:
        KeyError: If the record has no id.
        ValueError: If a value is not of the kind its setting takes.
    """
    patch = {key: record[key] for key in MONITOR_DEFAULTS if key in record}
    if "printer_id" in patch and patch["printer_id"] is None:
        patch["printer_id"] = ""
    return sanitise_monitor(record["id"], patch)


def persisted_monitor(record: dict[str, Any]) -> dict[str, Any]:
    """Keeps only a monitor's configuration, dropping runtime and retired fields."""
    return {k: record[k] for k in ("id", *MONITOR_DEFAULTS)}
