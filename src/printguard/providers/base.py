"""Base class for 3D printer providers."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCPeerConnection


class StatusSource(ABC):
    """Interface for providing printer status."""
    @abstractmethod
    async def is_printing(self) -> bool:
        """Return True if printer is actively printing."""
        ...


class CameraSource(ABC):
    """Interface for providing a camera feed."""
    @abstractmethod
    async def get_camera_track(self) -> Tuple[Optional["MediaStreamTrack"], Optional["RTCPeerConnection"]]:
        """Return a WebRTC video track and its peer connection."""
        ...


class ControlSink(ABC):
    """Interface for printer control commands."""
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def pause(self) -> None: ...
    @abstractmethod
    async def resume(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...


class PrinterProvider(StatusSource, CameraSource, ControlSink, ABC):
    """Base for standard all-in-one printer integrations."""
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        ...
