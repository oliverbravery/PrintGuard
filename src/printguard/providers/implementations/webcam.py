from typing import Optional, Tuple, TYPE_CHECKING
import logging
import asyncio
import cv2
from aiortc import MediaStreamTrack, RTCPeerConnection
from aiortc.contrib.media import MediaPlayer

from ..base import CameraSource
from ..registry import register
from ...services.streams import stream_manager

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCPeerConnection

logger = logging.getLogger(__name__)

@register("webcam")
class WebcamProvider(CameraSource):
    """Provider for browser webcams and IP/RTSP streams."""
    
    def __init__(self, type: str, url: Optional[str] = None, session_id: Optional[str] = None, device_id: Optional[str] = None, **kwargs):
        self.type = type
        self.url = url
        self.session_id = session_id or device_id
        self._player: Optional[MediaPlayer] = None

    @property
    def name(self) -> str:
        return "webcam"

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "connection_fields": [],
            "entity_fields": [
                {
                    "name": "type", 
                    "type": "select", 
                    "required": True, 
                    "label": "Source Type",
                    "options": [
                        {"label": "Browser Webcam", "value": "browser"},
                        {"label": "RTSP/IP Camera", "value": "rtsp"}
                    ]
                },
                {
                    "name": "device_id", 
                    "type": "device_select", 
                    "required": True, 
                    "label": "Select Camera",
                    "condition": "type == 'browser'"
                },
                {
                    "name": "url", 
                    "type": "string", 
                    "required": True, 
                    "label": "RTSP URL",
                    "condition": "type == 'rtsp'",
                    "placeholder": "rtsp://username:password@ip:port/path"
                }
            ]
        }

    @classmethod
    async def validate_component(cls, config: dict) -> bool:
        """Test connection to RTSP stream."""
        source_type = config.get("type")
        if source_type == "browser":
            # Browser webcams cannot be validated server-side without an active session
            return True
        elif source_type == "rtsp":
            url = config.get("url")
            if not url:
                return False
            try:
                loop = asyncio.get_event_loop()
                cap = await loop.run_in_executor(None, lambda: cv2.VideoCapture(url))
                is_opened = cap.isOpened()
                cap.release()
                return is_opened
            except Exception as e:
                logger.error(f"Webcam validation failed: {e}")
                return False
        return False

    @classmethod
    async def list_entities(cls, config: dict) -> list[dict]:
        """Return webcam entities."""
        source_type = config.get("type")
        if source_type == "browser":
            return [{"id": "browser_cam", "name": "Browser Webcam", "type": "camera"}]
        elif source_type == "rtsp":
            url = config.get("url", "RTSP Camera")
            return [{"id": "rtsp_cam", "name": url, "type": "camera"}]
        return []

    async def get_camera_track(self) -> Tuple[Optional[MediaStreamTrack], Optional[RTCPeerConnection]]:
        """Return a video track based on webcam type."""
        if self.type == "browser":
            if not self.session_id:
                logger.warning("Browser webcam requested but no session_id provided")
                return None, None
            source = stream_manager.get_source(self.session_id)
            if source:
                return source.track, source.pc
            return None, None
            
        elif self.type == "rtsp":
            if not self.url:
                logger.warning("RTSP webcam requested but no url provided")
                return None, None
            
            try:
                options = {
                    "fflags": "nobuffer",
                    "flags": "low_delay",
                    "probesize": "32",
                    "analyzeduration": "0",
                }
                player = MediaPlayer(self.url, options=options)
                if player.video:
                    self._player = player
                    return player.video, None
            except Exception as e:
                logger.error(f"Failed to open RTSP stream {self.url}: {e}")
                
        return None, None

    async def disconnect(self) -> None:
        """Close any active media players."""
        if self._player:
            self._player = None

