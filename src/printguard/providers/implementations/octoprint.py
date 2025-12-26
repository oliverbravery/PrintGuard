"""OctoPrint printer provider implementation."""

import httpx
import logging
import asyncio
from typing import Optional, Tuple

from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

from ..base import PrinterProvider
from ..registry import register

logger = logging.getLogger(__name__)

@register("octoprint")
class OctoPrintProvider(PrinterProvider):
    """Provider for OctoPrint API."""

    def __init__(self, host: str, api_key: str):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self.client: Optional[httpx.AsyncClient] = None
        self._pcs: set[RTCPeerConnection] = set()

    @property
    def name(self) -> str:
        return "octoprint"

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "connection_fields": [
                {"name": "host", "type": "string", "required": True, "label": "OctoPrint Host"},
                {"name": "api_key", "type": "password", "required": True, "label": "API Key"}
            ],
            "entity_fields": []
        }

    @classmethod
    async def validate_connection(cls, config: dict) -> bool:
        """Test connection to OctoPrint."""
        host = config.get("host", "").rstrip("/")
        api_key = config.get("api_key", "")
        if not host or not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{host}/api/version",
                    headers={"X-Api-Key": api_key}
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"OctoPrint validation failed: {e}")
            return False

    async def connect(self) -> None:
        """Initialize the HTTP client and test connection."""
        if not self.client:
            self.client = httpx.AsyncClient(base_url=self.host, headers=self.headers)
        # Test connection by getting connection settings
        response = await self.client.get("/api/connection")
        response.raise_for_status()
        # Ensure printer is connected in OctoPrint
        data = response.json()
        if data.get("current", {}).get("state") == "Closed":
            await self.client.post("/api/connection", json={"command": "connect"})

    async def disconnect(self) -> None:
        """Close the HTTP client and any active peer connections."""
        for pc in list(self._pcs):
            await pc.close()
        self._pcs.clear()

        if self.client:
            await self.client.aclose()
            self.client = None

    async def is_printing(self) -> bool:
        """Check if the printer is currently printing."""
        if not self.client:
            await self.connect()
        response = await self.client.get("/api/job")
        response.raise_for_status()
        data = response.json()
        return data.get("state") == "Printing"

    async def start(self) -> None:
        """Start the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "start"})
        response.raise_for_status()

    async def get_camera_track(self) -> Tuple[Optional[MediaStreamTrack], Optional[RTCPeerConnection]]:
        """Return a WebRTC video track from OctoPrint's camera-streamer."""
        if not self.client:
            await self.connect()
        try:
            resp = await self.client.get("/api/webcam/webcams")
            resp.raise_for_status()
            webcams = resp.json()
            if not webcams:
                logger.warning("No webcams found in OctoPrint")
                return None, None
            stream_url = webcams[0].get("compat", {}).get("stream", "")
            if not stream_url:
                logger.warning("Primary webcam has no stream URL")
                return None, None
            base_path = stream_url.split('?')[0].rstrip('/')
            if base_path.startswith("/"):
                signaling_url = f"{self.host}{base_path}/api/v1/stream/webrtc"
            else:
                signaling_url = f"{base_path}/api/v1/stream/webrtc"
        except Exception as e:
            logger.warning(f"Failed to discover OctoPrint webcam: {e}")
            return None, None
        # WebRTC Handshake with camera-streamer
        pc = RTCPeerConnection()
        self._pcs.add(pc)
        pc.addTransceiver("video", direction="recvonly")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    signaling_url,
                    json={"type": "offer", "sdp": pc.localDescription.sdp},
                    timeout=10.0
                )
                resp.raise_for_status()
                answer_data = resp.json()
            answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
            await pc.setRemoteDescription(answer)
        except Exception as e:
            logger.warning(f"WebRTC signaling failed with camera-streamer at {signaling_url}: {e}")
            await pc.close()
            self._pcs.discard(pc)
            return None, None
        # Wait for the track to be received
        track_event = asyncio.Event()
        remote_track: Optional[MediaStreamTrack] = None

        @pc.on("track")
        def on_track(track):
            nonlocal remote_track
            if track.kind == "video":
                remote_track = track
                track_event.set()

        try:
            await asyncio.wait_for(track_event.wait(), timeout=10.0)
            return remote_track, pc
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for OctoPrint camera track")
            await pc.close()
            self._pcs.discard(pc)
            return None, None

    async def pause(self) -> None:
        """Pause the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "pause", "action": "pause"})
        response.raise_for_status()

    async def resume(self) -> None:
        """Resume the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "pause", "action": "resume"})
        response.raise_for_status()

    async def stop(self) -> None:
        """Cancel the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "cancel"})
        response.raise_for_status()