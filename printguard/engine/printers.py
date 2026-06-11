"""Printer configuration: defaults, validation and serialisation."""

from __future__ import annotations

from typing import Any

PRINTER_DEFAULTS: dict[str, Any] = {
    "name": "Printer",
    "camera_id": "",
    "enabled": True,
    "threshold": 0.75,
    "sensitivity": 1.0,
    "consecutive": 3,
    "notify": False,
    "device": {
        "provider": None,
        "config": {},
        "on_defect": "none",
        "cooldown_s": 60,
    },
}

_CLAMPS = {"threshold": (0.05, 1.0), "sensitivity": (0.2, 5.0), "consecutive": (1, 30), "cooldown_s": (0, 600)}


def _clamp(key: str, value: float) -> float:
    low, high = _CLAMPS[key]
    return max(low, min(high, value))


def sanitise_printer(printer_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a printer patch over defaults or an existing record.

    Args:
        printer_id: Stable identifier for the printer.
        patch: Partial printer fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated printer record.
    """
    record = {**(base or PRINTER_DEFAULTS), **patch, "id": printer_id}
    device = {**PRINTER_DEFAULTS["device"], **(base or {}).get("device", {}), **patch.get("device", {})}
    record["device"] = device
    record["name"] = str(record["name"]).strip() or "Printer"
    record["threshold"] = _clamp("threshold", float(record["threshold"]))
    record["sensitivity"] = _clamp("sensitivity", float(record["sensitivity"]))
    record["consecutive"] = int(_clamp("consecutive", int(record["consecutive"])))
    record["enabled"] = bool(record["enabled"])
    record["notify"] = bool(record["notify"])
    device["cooldown_s"] = int(_clamp("cooldown_s", int(device["cooldown_s"])))
    if device["on_defect"] not in ("none", "pause", "cancel"):
        device["on_defect"] = "none"
    return record


def persisted_printer(record: dict[str, Any]) -> dict[str, Any]:
    """Strips runtime-only fields before persistence."""
    return {k: v for k, v in record.items() if k not in ("device_state", "alert")}
