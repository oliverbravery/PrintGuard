from typing import Optional, Tuple, TYPE_CHECKING
from ..base import CameraSource
from ..registry import register
from ...services.streams import stream_manager

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCPeerConnection

@register("webrtc")
class WebRTCProvider(CameraSource):
    """Provider for standalone WebRTC camera streams."""
    
    def __init__(self, session_id: str, **kwargs):
        self.session_id = session_id

    @property
    def name(self) -> str:
        return "webrtc"

    async def connect(self) -> None:
        """No-op: connection is handled by the incoming WebRTC offer."""
        pass

    async def disconnect(self) -> None:
        """No-op."""
        pass

    async def get_camera_track(self) -> Tuple[Optional["MediaStreamTrack"], Optional["RTCPeerConnection"]]:
        """Retrieve the track from the stream manager."""
        source = stream_manager.get_source(self.session_id)
        if source:
            return source.track, source.pc
        return None, None

