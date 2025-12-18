"""Base class for 3D printer providers."""

from abc import ABC, abstractmethod


class PrinterProvider(ABC):
    """Abstract base for 3D printer integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'octoprint', 'homeassistant')."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the printer."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        ...

    @abstractmethod
    async def is_printing(self) -> bool:
        """Return True if printer is actively printing."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start/resume the print job."""
        ...

    @abstractmethod
    async def pause(self) -> None:
        """Pause the current print."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop/cancel the current print."""
        ...
