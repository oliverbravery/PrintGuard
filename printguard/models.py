import asyncio
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, field_validator, Field

class Alert(BaseModel):
    id: str
    snapshot: bytes
    title: str
    message: str
    timestamp: float
    countdown_time: float
    camera_uuid: str
    has_printer: bool = False
    countdown_action: str = "dismiss"

class AlertAction(str, Enum):
    DISMISS = "dismiss"
    CANCEL_PRINT = "cancel_print"
    PAUSE_PRINT = "pause_print"

class SSEDataType(str, Enum):
    ALERT = "alert"
    CAMERA_STATE = "camera_state"
    PRINTER_STATE = "printer_state"

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

class FileInfo(BaseModel):
    name: Optional[str] = None
    origin: Optional[str] = None
    size: Optional[int] = None
    date: Optional[int] = None


class Progress(BaseModel):
    completion: Optional[float] = None
    filepos: Optional[int] = None
    printTime: Optional[int] = None
    printTimeLeft: Optional[int] = None


class JobInfoResponse(BaseModel):
    job: Dict = Field(default_factory=dict)
    progress: Optional[Progress] = None
    state: str
    error: Optional[str] = None

    model_config = {
        "extra": "ignore"
    }


class TemperatureReading(BaseModel):
    actual: float
    target: Optional[float]
    offset: Optional[float]


class TemperatureReadings(BaseModel):
    temperature: Dict[str, TemperatureReading]
    
class PrinterTemperatures(BaseModel):
    nozzle_actual: Optional[float] = None
    nozzle_target: Optional[float] = None
    bed_actual: Optional[float] = None
    bed_target: Optional[float] = None

class PrinterState(BaseModel):
    jobInfoResponse: Optional[JobInfoResponse] = None
    temperatureReading: Optional[PrinterTemperatures] = None

class CurrentPayload(BaseModel):
    state: dict
    job: Any
    progress: Progress
    temps: Optional[list] = Field(None, alias="temps")

class PrinterType(str, Enum):
    OCTOPRINT = "octoprint"

class PrinterConfig(BaseModel):
    name: str
    printer_type: PrinterType
    camera_uuid: str
    base_url: str
    api_key: str

class PrinterConfigRequest(BaseModel):
    name: str
    printer_type: PrinterType
    camera_uuid: str
    base_url: str
    api_key: str

class CameraState(BaseModel):
    nickname: str
    source: str
    lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    current_alert_id: Optional[str] = None
    detection_history: List[tuple] = []
    live_detection_running: bool = False
    live_detection_task: Optional[str] = None
    last_result: Optional[str] = None
    last_time: Optional[float] = None
    start_time: Optional[float] = None
    error: Optional[str] = None
    brightness: float = None
    contrast: float = None
    focus: float = None
    sensitivity: float = None
    countdown_time: float = None
    countdown_action: str = None
    majority_vote_threshold: int = None
    majority_vote_window: int = None
    printer_id: Optional[str] = None
    printer_config: Optional[Dict] = None

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

class OperatingSystem(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"

class TunnelSettings(BaseModel):
    provider: TunnelProvider
    token: str
    domain: str = ""
    email: Optional[str] = None

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
    TUNNEL_TOKEN = "tunnel_token"

class SavedConfig(str, Enum):
    VERSION = "version"
    VAPID_SUBJECT = "vapid_subject"
    VAPID_PUBLIC_KEY = "vapid_public_key"
    STARTUP_MODE = "startup_mode"
    SITE_DOMAIN = "site_domain"
    TUNNEL_PROVIDER = "tunnel_provider"
    CLOUDFLARE_EMAIL = "cloudflare_email"
    CLOUDFLARE_TEAM_NAME = "cloudflare_team_name"
    USER_OPERATING_SYSTEM = "user_operating_system"
    STREAM_OPTIMIZE_FOR_TUNNEL = "stream_optimize_for_tunnel"
    STREAM_MAX_FPS = "stream_max_fps"
    STREAM_TUNNEL_FPS = "stream_tunnel_fps"
    STREAM_JPEG_QUALITY = "stream_jpeg_quality"
    STREAM_MAX_WIDTH = "stream_max_width"
    DETECTION_INTERVAL_MS = "detection_interval_ms"
    PRINTER_STAT_POLLING_RATE_MS = "printer_stat_polling_rate_ms"
    MIN_SSE_DISPATCH_DELAY_MS = "min_sse_dispatch_delay_ms"
    PUSH_SUBSCRIPTIONS = "push_subscriptions"
    CAMERA_STATES = "camera_states"

class CloudflareTunnelConfig(BaseModel):
    account_id: str
    zone_id: str
    subdomain: str

class CloudflareDownloadConfig(BaseModel):
    operating_system: OperatingSystem

class WarpDeviceConfig(BaseModel):
    device_id: Optional[str] = None
    user_email: Optional[str] = None

class CloudflareCommandSet(BaseModel):
    operating_system: OperatingSystem
    install_command: str
    enable_command: str = ""
    start_command: str
    stop_command: str
    restart_command: str = ""
    setup_sequence: List[str]

class WarpDeviceEnrollmentRule(BaseModel):
    name: str
    precedence: int = 0
    require: List[str] = []
    include: List[str] = []

class FeedSettings(BaseModel):
    stream_max_fps: int
    stream_tunnel_fps: int
    stream_jpeg_quality: int
    stream_max_width: int
    detections_per_second: int
    detection_interval_ms: int
    printer_stat_polling_rate_ms: int
    min_sse_dispatch_delay_ms: int

class PollingTask(BaseModel):
    task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None
    model_config = {
        "arbitrary_types_allowed": True
    }
