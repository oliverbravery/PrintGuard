"""Shared contract for pluggable service adapters.

Adapters (printer integrations, alert notifiers) are shared code: they
talk to external services only through the platform's HTTP function, so
the same adapter runs in the browser (local mode) and on the server (hub
mode).
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Awaitable, Callable

HttpFn = Callable[..., Awaitable[tuple[int, Any]]]


class Adapter(ABC):
    """Base class for schema-configured service adapters.

    Attributes:
        id: Registry key and protocol identifier.
        label: Human-readable service name.
        docs_url: Link to the official API reference the adapter is built
            against; mandatory so reviewers can verify behaviour.
        browser_ok: Whether the adapter can run in local (browser) mode.
            Adapters needing a transport the browser sandbox forbids — a
            raw socket, or HTTP to a service without CORS headers — set
            this False and are offered in hub mode only.
        schema: JSON Schema describing the configuration form. Property
            extensions: "secret" marks sensitive fields, "placeholder"
            provides input hints.
    """

    id: str
    label: str
    docs_url: str
    browser_ok: bool = True
    schema: dict[str, Any]

    def meta(self) -> dict[str, Any]:
        """Serialises adapter metadata for schema-driven configuration UIs."""
        return {"id": self.id, "label": self.label, "docs_url": self.docs_url, "browser_ok": self.browser_ok, "schema": self.schema}
