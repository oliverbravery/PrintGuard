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

def _get_config_value(key: str):
    # pylint: disable=import-outside-toplevel
    from .utils.config import (BRIGHTNESS, CONTRAST,
                              FOCUS, SENSITIVITY,
                              COUNTDOWN_TIME, COUNTDOWN_ACTION,
                              DETECTION_VOTING_THRESHOLD,
                              DETECTION_VOTING_WINDOW)
    config_map = {
        'BRIGHTNESS': BRIGHTNESS,
        'CONTRAST': CONTRAST,
        'FOCUS': FOCUS,
        'SENSITIVITY': SENSITIVITY,
        'COUNTDOWN_TIME': COUNTDOWN_TIME,
        'COUNTDOWN_ACTION': COUNTDOWN_ACTION,
        'DETECTION_VOTING_THRESHOLD': DETECTION_VOTING_THRESHOLD,
        'DETECTION_VOTING_WINDOW': DETECTION_VOTING_WINDOW,
    }
    return config_map[key]

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
    brightness: int = None
    contrast: int = None
    focus: int = None
    sensitivity: int = None
    countdown_time: float = None
    countdown_action: str = None
    majority_vote_threshold: int = None
    majority_vote_window: float = None

    def __init__(self, **data):
        if 'brightness' not in data:
            data['brightness'] = _get_config_value('BRIGHTNESS')
        if 'contrast' not in data:
            data['contrast'] = _get_config_value('CONTRAST')
        if 'focus' not in data:
            data['focus'] = _get_config_value('FOCUS')
        if 'sensitivity' not in data:
            data['sensitivity'] = _get_config_value('SENSITIVITY')
        if 'countdown_time' not in data:
            data['countdown_time'] = _get_config_value('COUNTDOWN_TIME')
        if 'countdown_action' not in data:
            data['countdown_action'] = _get_config_value('COUNTDOWN_ACTION')
        if 'majority_vote_threshold' not in data:
            data['majority_vote_threshold'] = _get_config_value('DETECTION_VOTING_THRESHOLD')
        if 'majority_vote_window' not in data:
            data['majority_vote_window'] = _get_config_value('DETECTION_VOTING_WINDOW')
        super().__init__(**data)
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

class SetupCompletion(BaseModel):
    startup_mode: SiteStartupMode
    tunnel_provider: Optional[TunnelProvider] = None

class SavedKey(str, Enum):
    VAPID_PRIVATE_KEY = "vapid_private_key"
    SSL_PRIVATE_KEY = "ssl_private_key"
    TUNNEL_API_KEY = "tunnel_api_key"

class SavedConfig(str, Enum):
    VAPID_SUBJECT = "vapid_subject"
    VAPID_PUBLIC_KEY = "vapid_public_key"
    STARTUP_MODE = "startup_mode"
    SITE_DOMAIN = "site_domain"
    TUNNEL_PROVIDER = "tunnel_provider"
