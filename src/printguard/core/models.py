"""Pydantic models for API."""

from typing import Optional, Any
from enum import Enum

from pydantic import BaseModel


class FeedSettings(BaseModel):
    """Settings for a camera feed."""
    resolution: tuple[int, int] = (640, 480)
    brightness: float = 1.0
    contrast: float = 1.0
    sensitivity: float = 1.0


class RTCOffer(BaseModel):
    """WebRTC offer from client."""
    sdp: str
    type: str
    session_id: str
    settings: FeedSettings = FeedSettings()
    device_name: str = "Camera"
    printer_id: Optional[str] = None


class PushSubscriptionInfo(BaseModel):
    """Browser push subscription info."""
    endpoint: str
    keys: dict[str, str]


class PushSubscription(BaseModel):
    """Push subscription request."""
    session_id: str
    device_name: str
    subscription: PushSubscriptionInfo


class SessionSubscription(BaseModel):
    """Push subscription stored per session."""
    subscription: PushSubscriptionInfo
    device_name: str


class Session(BaseModel):
    """WebRTC session state."""
    pc: Any = None
    processor: Any = None
    device_name: str = "Camera"
    settings: FeedSettings = FeedSettings()

    model_config = {"arbitrary_types_allowed": True}


class StreamInfo(BaseModel):
    """Information about an active stream."""
    session_id: str
    device_name: str
    settings: FeedSettings


class RTCAnswer(BaseModel):
    """WebRTC answer to client."""
    sdp: str
    type: str


class PredictionStatus(str, Enum):
    """Status of a prediction."""
    SUCCESS = "success"
    WAITING = "waiting"
    ERROR = "error"


class PredictionClass(str, Enum):
    """Common prediction classes."""
    NORMAL = "normal"
    DEFECT = "defect"


class PredictionResult(BaseModel):
    """Prediction result for a frame."""
    class_name: Optional[PredictionClass | str] = None
    class_idx: Optional[int] = None
    confidence: Optional[float] = None
    distances: Optional[dict[str, float]] = None
    status: PredictionStatus = PredictionStatus.SUCCESS


class CFAccount(BaseModel):
    """Cloudflare account info."""
    id: str
    name: str


class CFZone(BaseModel):
    """Cloudflare zone info."""
    id: str
    name: str


class CFTunnel(BaseModel):
    """Cloudflare tunnel info."""
    id: str
    name: str
    tunnel_secret: str = ""
    account_id: str = ""


class CFDNSRecord(BaseModel):
    """Cloudflare DNS record info."""
    id: str
    name: str


class CFTunnelRequest(BaseModel):
    """Request to create a Cloudflare tunnel."""
    account_id: str
    zone_id: str
    tunnel_name: str
    subdomain: str = "camera"
    overwrite_tunnel: bool = False
    overwrite_dns: bool = False


class CFExistenceResponse(BaseModel):
    """Response checking if Cloudflare resources exist."""
    tunnel_exists: bool
    dns_exists: bool


class DependencyStatus(BaseModel):
    """Installation status of external dependencies."""
    ngrok_installed: bool
    cloudflared_installed: bool


class CFTunnelResponse(BaseModel):
    """Response after creating a Cloudflare tunnel."""
    tunnel_id: str
    tunnel_secret: str
    url: str


class NgrokTunnelRequest(BaseModel):
    """Request to create an ngrok tunnel."""
    authtoken: str
    domain: Optional[str] = None
    edge: Optional[str] = None


class NgrokTunnelResponse(BaseModel):
    """Response after creating an ngrok tunnel."""
    url: str


class TunnelStatus(BaseModel):
    """Current tunnel status."""
    provider: str
    url: Optional[str] = None
    is_active: bool


class PrinterStatus(str, Enum):
    """Printer state."""
    IDLE = "idle"
    PRINTING = "printing"
    PAUSED = "paused"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ComponentConfig(BaseModel):
    """Configuration for a single printer component."""
    id: Optional[str] = None
    name: Optional[str] = None
    provider: Optional[str] = None
    config: dict = {}


class ComponentInfo(BaseModel):
    """Full component information."""
    id: str
    name: Optional[str] = None
    type: str
    provider: str
    entity_config: dict = {}


class PrinterComponents(BaseModel):
    """Modular printer components."""
    status: Optional[ComponentConfig | str] = None
    camera: Optional[ComponentConfig | str] = None
    control: Optional[ComponentConfig | str] = None


class PrinterConfig(BaseModel):
    """Configuration for a printer instance."""
    id: Optional[str] = None
    name: str
    components: PrinterComponents
    linked_session_id: Optional[str] = None
    client_public_key: Optional[str] = None


class PrinterInfo(BaseModel):
    """Printer status response."""
    id: str
    name: str
    status: PrinterStatus
    linked_session_id: Optional[str] = None
    has_control: bool = False
    has_camera: bool = False
    components: Optional[dict[str, ComponentInfo]] = None


class ConnectionInfo(BaseModel):
    """Connection information."""
    id: str
    name: str
    provider: str
    config: dict


class ConnectionCreate(BaseModel):
    """Request to create a new connection."""
    name: str
    provider: str
    config: dict


class ConnectionUpdate(BaseModel):
    """Request to update a connection."""
    name: Optional[str] = None
    config: Optional[dict] = None


class ComponentCreate(BaseModel):
    """Request to create a new component."""
    name: str
    type: str  # camera, control, status
    provider: str
    connection_id: Optional[str] = None
    entity_config: dict = {}


class ComponentUpdate(BaseModel):
    """Request to update a component."""
    name: Optional[str] = None
    entity_config: Optional[dict] = None


class PrinterUpdate(BaseModel):
    """Request to update a printer."""
    name: Optional[str] = None
    components: Optional[PrinterComponents] = None
