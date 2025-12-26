"""Base class for 3D printer providers."""

from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCPeerConnection


class BaseProvider(ABC):
    """Base interface for all provider types."""
    @classmethod
    def get_schema(cls) -> dict:
        """Return the configuration schema for this provider."""
        return {"connection_fields": [], "entity_fields": []}

    @classmethod
    async def validate_connection(cls, config: dict) -> bool:
        """Test if the connection configuration is valid and reachable."""
        return True

    @classmethod
    async def validate_component(cls, config: dict) -> bool:
        """Test if the component configuration (including entity) is valid."""
        return await cls.validate_connection(config)

    @classmethod
    async def list_entities(cls, config: dict) -> list[dict]:
        """Fetch available entities from the provider."""
        return []


class StatusSource(BaseProvider, ABC):
    """Interface for providing printer status."""
    @abstractmethod
    async def is_printing(self) -> bool:
        """Return True if printer is actively printing."""
        ...


class CameraSource(BaseProvider, ABC):
    """Interface for providing a camera feed."""
    @abstractmethod
    async def get_camera_track(self) -> Tuple[Optional["MediaStreamTrack"], Optional["RTCPeerConnection"]]:
        """Return a WebRTC video track and its peer connection."""
        ...


class ControlSink(BaseProvider, ABC):
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
