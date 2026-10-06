"""Printer configuration, validating registered integrated printers, the
heater targets they are sent and the preheat presets that fill those in.

A printer is a connection to a control service (OctoPrint, Klipper/Moonraker,
Elegoo, PrusaLink, Bambu, …) identified by an integration provider and its schema-driven config.
"""

from __future__ import annotations

from typing import Any

from .bounds import HEATER_MAX, clamp
from .integrations import HEATERS, INTEGRATIONS

PRESET_NAME_MAX = 20
PRESETS_MAX = 12
PREHEAT_DEFAULTS: list[dict[str, Any]] = [
    {"name": "PLA", "nozzle": 210, "bed": 60},
    {"name": "PETG", "nozzle": 240, "bed": 85},
    {"name": "ABS", "nozzle": 250, "bed": 100},
]


def sanitise_printer(printer_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a printer patch over an existing record and validates the provider.

    Args:
        printer_id: Stable identifier for the printer.
        patch: Partial printer fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated printer record: id, name, provider and config.

    Raises:
        ValueError: If the provider is missing or not a known integration.
    """
    record = {**(base or {}), **patch, "id": printer_id}
    provider = record.get("provider")
    if provider not in INTEGRATIONS:
        raise ValueError(f"unknown printer provider {provider!r}")
    record["provider"] = provider
    record["name"] = (str(record.get("name") or "").strip()) or INTEGRATIONS[provider].label
    record["config"] = dict(record.get("config") or {})
    return record


def _target(heater: str, value: Any, strict: bool = False) -> float:
    degrees = clamp(f"{heater} temperature", value, 0.0, HEATER_MAX[heater])
    if strict and degrees != value:
        raise ValueError(f"{heater} temperature must be a number from 0 to {HEATER_MAX[heater]:g}")
    return degrees


def sanitise_targets(fields: dict[str, Any], strict: bool = False) -> dict[str, float]:
    """The heater targets a command names.

    Args:
        fields: A mapping that may carry a value under each of ``HEATERS``.
        strict: Whether to refuse a target outside what a hotend or bed can
            take, or one that is not a number, instead of clamping it.

    Returns:
        Heater name to target in degrees Celsius, for the heaters named.

    Raises:
        ValueError: If a target is not a finite number, or strict and it is
            out of range.
    """
    return {heater: _target(heater, fields[heater], strict) for heater in HEATERS if fields.get(heater) is not None}


def sanitise_presets(raw: Any) -> list[dict[str, Any]]:
    """Validates preheat presets: a bounded name and a clamped target per heater.

    Args:
        raw: The presets as the UI supplied them.

    Returns:
        The presets that carry a name, capped at ``PRESETS_MAX``.

    Raises:
        ValueError: If the presets are not a list of presets, or a target is
            not a finite number.
    """
    if not isinstance(raw, list) or not all(isinstance(preset, dict) for preset in raw):
        raise ValueError("preheat is a list of presets, each with a name and a nozzle and bed target")
    presets = []
    for preset in raw:
        name = " ".join(str(preset.get("name") or "").split())[:PRESET_NAME_MAX]
        if name:
            presets.append({"name": name, **{heater: _target(heater, preset.get(heater) or 0) for heater in HEATERS}})
    return presets[:PRESETS_MAX]
