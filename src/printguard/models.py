"""Pydantic models for API."""

from typing import TYPE_CHECKING, Optional
from enum import Enum

from pydantic import BaseModel

if TYPE_CHECKING:
    from aiortc import RTCPeerConnection
    from .webrtc import VideoProcessor


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
    pc: "RTCPeerConnection"
    processor: "VideoProcessor"
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


class CFTunnelRequest(BaseModel):
    """Request to create a Cloudflare tunnel."""
    account_id: str
    zone_id: str
    tunnel_name: str
    subdomain: str = "camera"


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
