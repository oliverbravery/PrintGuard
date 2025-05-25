import asyncio
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, field_validator


class Alert(BaseModel):
    id: str
    snapshot: bytes
    title: str
    message: str
    timestamp: float
    countdown_time: float
    camera_index: int

class AlertAction(str, Enum):
    DISMISS = "dismiss"
    CANCEL_PRINT = "cancel_print"

class SSEDataType(str, Enum):
    ALERT = "alert"
    CAMERA_STATE = "camera_state"

class NotificationAction(BaseModel):
    action: str
    title: str
    icon: Optional[str] = None

class Notification(BaseModel):
    title: str
    body: str
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    badge_url: Optional[str] = None
    actions: List[NotificationAction] = []

# pylint: disable=C0413
from .utils import config


class CameraState(BaseModel):
    lock: asyncio.Lock = asyncio.Lock()
    current_alert_id: Optional[str] = None
    detection_history: List[tuple] = []
    live_detection_running: bool = False
    live_detection_task: Optional[str] = None
    last_result: Optional[str] = None
    last_time: Optional[float] = None
    start_time: Optional[float] = None
    error: Optional[str] = None
    brightness: int = config.BRIGHTNESS
    contrast: int = config.CONTRAST
    focus: int = config.FOCUS
    sensitivity: int = config.SENSITIVITY
    countdown_time: float = config.COUNTDOWN_TIME
    countdown_action: str = config.COUNTDOWN_ACTION
    majority_vote_threshold: int = config.DETECTION_VOTING_THRESHOLD
    majority_vote_window: float = config.DETECTION_VOTING_WINDOW
    model_config = {
        "arbitrary_types_allowed": True
    }

class VapidSettings(BaseModel):
    public_key: str
    private_key: str
    subject: str
    base_url: str
    
class SiteStartupMode(str, Enum):
    SETUP = "setup"
    LOCAL = "local"
    TUNNEL = "tunnel"

class TunnelProvider(str, Enum):
    NGROK = "ngrok"
    CLOUDFLARE = "cloudflare"

class TunnelSettings(BaseModel):
    provider: TunnelProvider
    token: str
    domain: str = ""
    
    @field_validator('domain')
    @classmethod
    def validate_domain_for_ngrok(cls, v, info):
        if info.data.get('provider') == TunnelProvider.NGROK and not v:
            raise ValueError('Domain is required for ngrok provider')
        return v

class SavedKey(str, Enum):
    VAPID_PRIVATE_KEY = "vapid_private_key"
    SSL_PRIVATE_KEY = "ssl_private_key"
    TUNNEL_API_KEY = "tunnel_api_key"
