"""Pydantic models for API."""

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from aiortc import RTCPeerConnection
    from .webrtc import VideoProcessor


class RTCOffer(BaseModel):
    """WebRTC offer from client."""
    sdp: str
    type: str
    session_id: str
    sensitivity: float = 1.0
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

    model_config = {"arbitrary_types_allowed": True}
