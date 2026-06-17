"""Printer configuration: validation for registered integrated printers.

A printer is a connection to a control service (OctoPrint, Klipper/Moonraker,
Bambu, …) identified by an integration provider and its schema-driven config.
"""

from __future__ import annotations

from typing import Any

from .integrations import INTEGRATIONS


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
