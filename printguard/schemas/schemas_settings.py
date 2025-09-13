from enum import Enum
from pydantic import BaseModel

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

class FeedSettings(BaseModel):
    stream_max_fps: int
    stream_tunnel_fps: int
    stream_jpeg_quality: int
    stream_max_width: int
    detections_per_second: int
    detection_interval_ms: int
    printer_stat_polling_rate_ms: int
    min_sse_dispatch_delay_ms: int