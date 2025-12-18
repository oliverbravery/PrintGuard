"""Base class for 3D printer providers."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCPeerConnection


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
    async def resume(self) -> None:
        """Resume the current print."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop/cancel the current print."""
        ...

    @abstractmethod
    async def get_camera_track(self) -> Tuple[Optional["MediaStreamTrack"], Optional["RTCPeerConnection"]]:
        """Return a WebRTC video track and its peer connection for the printer's camera."""
        ...
