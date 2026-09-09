"""Contract for printer service integrations.

An integration adapter is shared code: it talks to the printer service
through the platform's HTTP function, so the same adapter runs in the
browser (local mode) and on the server (hub mode). Contributors add a
service by subclassing IntegrationAdapter in a new module and registering
an instance in printguard.engine.integrations.INTEGRATIONS.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..adapters import Adapter, HttpFn

HEATERS = ("nozzle", "bed")
"""The heaters every service is read and controlled through, by PrintGuard's names."""


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
class Heater:
    """A heater's reading and the target it is holding, in degrees Celsius.

    Attributes:
        actual: The temperature the service last reported.
        target: The temperature it is heading for, 0 when the heater is off.
    """

    actual: float
    target: float

    @classmethod
    def reported(cls, actual: Any, target: Any) -> Heater | None:
        """Builds a heater from a service's reading and target.

        Args:
            actual: The reported temperature, or None where the service has
                no such heater or is not reporting it.
            target: The reported target, taken as off when missing.

        Returns:
            The heater, or None when there is no reading.
        """
        if actual is None:
            return None
        return cls(float(actual), float(target or 0.0))

    def public(self) -> dict[str, float]:
        """Serialises the heater for the event protocol."""
        return {"actual": round(self.actual, 1), "target": round(self.target, 1)}


@dataclass
class DeviceState:
    """Normalised snapshot of a printer.

    Attributes:
        status: Canonical printer state.
        progress: Job completion percentage in [0, 100].
        job: Name of the active job file, if any.
        remaining_s: Seconds the service expects the job to take from now,
            or None where it does not say.
        nozzle: The hotend, or None where the service reports none.
        bed: The heated bed, or None where the service reports none.
    """

    status: DeviceStatus
    progress: float = 0.0
    job: str | None = None
    remaining_s: int | None = None
    nozzle: Heater | None = None
    bed: Heater | None = None

    def public(self) -> dict[str, Any]:
        """Serialises the state for the event protocol."""
        return {
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "job": self.job,
            "remaining_s": self.remaining_s,
            "nozzle": self.nozzle.public() if self.nozzle else None,
            "bed": self.bed.public() if self.bed else None,
        }


class IntegrationAdapter(Adapter):
    """Base class for printer service integrations.

    Attributes:
        formats: File extensions, without the dot, the service prints from an
            upload. Empty means it takes no files, which is the default.
        heater_control: Whether the service takes heater targets through
            ``heat()``. Every service reports the temperatures it has; this is
            about setting them, which is off by default.
    """

    formats: tuple[str, ...] = ()
    heater_control: bool = False

    def meta(self) -> dict[str, Any]:
        """Serialises adapter metadata, with the formats it prints and whether it heats."""
        return {**super().meta(), "formats": list(self.formats), "heater_control": self.heater_control}

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

    async def heat(self, http: HttpFn, config: dict[str, Any], heater: str, target: float) -> None:
        """Sets one heater's target temperature.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.
            heater: One of ``HEATERS``.
            target: Degrees Celsius, 0 to turn the heater off.

        Raises:
            RuntimeError: If the service rejects the target, or takes none.
        """
        raise RuntimeError(f"{self.label} cannot set heater targets")

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Lists the cameras the printer service currently exposes.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.

        Returns:
            One descriptor per camera, each a dict of ``key`` (a stable
            identifier for the camera within this printer), ``name`` and
            ``source`` (an engine camera source dict). The default is empty,
            for services without a camera. The engine re-queries this, so a
            camera attached to the service after the printer was registered is
            picked up automatically.
        """
        return []

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Uploads a sliced file to the service and starts printing it.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.
            filename: Name the file is given on the service, carrying one of
                the adapter's ``formats`` as its extension.
            data: The file's bytes.

        Raises:
            RuntimeError: If the service rejects the file or the print.
        """
        raise RuntimeError(f"{self.label} cannot receive print files")

    async def close(self, config: dict[str, Any] | None = None) -> None:
        """Releases persistent connections for one configuration or all configurations."""
