"""Printer service integration registry.

To add a service: create a module in this package with an
IntegrationAdapter subclass and register an instance below. The
configuration form, device polling and defect actions follow from the
adapter alone — no other code changes are required in either mode.
"""

from __future__ import annotations

from typing import Any

from .bambu import BambuAdapter
from .base import DeviceAction, DeviceState, DeviceStatus, IntegrationAdapter
from .klipper import KlipperAdapter
from .octoprint import OctoPrintAdapter
from .prusa import PrusaAdapter

INTEGRATIONS: dict[str, IntegrationAdapter] = {
    adapter.id: adapter for adapter in (OctoPrintAdapter(), KlipperAdapter(), PrusaAdapter(), BambuAdapter())
}


def integrations_meta() -> list[dict[str, Any]]:
    """Serialises every adapter's metadata for configuration UIs."""
    return [adapter.meta() for adapter in INTEGRATIONS.values()]


__all__ = [
    "DeviceAction",
    "DeviceState",
    "DeviceStatus",
    "IntegrationAdapter",
    "INTEGRATIONS",
    "integrations_meta",
]
