"""Contract for printer service integrations.

An integration adapter is shared code: it talks to the printer service
through the platform's HTTP function, so the same adapter runs in the
browser (local mode) and on the server (hub mode). Contributors add a
service by subclassing IntegrationAdapter in a new module and registering
an instance in printguard.engine.integrations.INTEGRATIONS.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable

HttpFn = Callable[..., Awaitable[tuple[int, Any]]]


class DeviceStatus(str, Enum):
    """Canonical printer states every adapter normalises to."""

    PRINTING = "printing"
    PAUSED = "paused"
    IDLE = "idle"
    ERROR = "error"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class DeviceAction(str, Enum):
    """Commands a printer service must support."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


@dataclass
class DeviceState:
    """Normalised snapshot of a printer.

    Attributes:
        status: Canonical printer state.
        progress: Job completion percentage in [0, 100].
        job: Name of the active job file, if any.
    """

    status: DeviceStatus
    progress: float = 0.0
    job: str | None = None

    def public(self) -> dict[str, Any]:
        """Serialises the state for the event protocol."""
        return {"status": self.status.value, "progress": round(self.progress, 1), "job": self.job}


class IntegrationAdapter(ABC):
    """Base class for printer service integrations.

    Attributes:
        id: Registry key and protocol identifier.
        label: Human-readable service name.
        docs_url: Link to the official API reference the adapter is built
            against; mandatory so reviewers can verify behaviour.
        schema: JSON Schema describing the configuration form. Property
            extensions: "secret" marks sensitive fields, "placeholder"
            provides input hints.
    """

    id: str
    label: str
    docs_url: str
    schema: dict[str, Any]

    @abstractmethod
    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Queries the service and returns its normalised state.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.

        Returns:
            The printer's current DeviceState.
        """

    @abstractmethod
    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Sends a control action to the service.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.
            action: Action to perform.

        Raises:
            RuntimeError: If the service rejects the command.
        """

    def meta(self) -> dict[str, Any]:
        """Serialises adapter metadata for schema-driven configuration UIs."""
        return {"id": self.id, "label": self.label, "docs_url": self.docs_url, "schema": self.schema}
