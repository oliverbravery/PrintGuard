"""Home Assistant printer provider implementation."""

from typing import Optional, Tuple
import logging
import asyncio
import httpx

from aiortc import RTCPeerConnection, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer

from ..base import PrinterProvider
from ..registry import register

logger = logging.getLogger(__name__)

@register("homeassistant")
class HomeAssistantProvider(PrinterProvider):
    """Provider for Home Assistant API."""

    def __init__(self, hass_url: str, token: str, entity_id: str, 
                 start_entity_id: Optional[str] = None,
                 pause_entity_id: Optional[str] = None,
                 resume_entity_id: Optional[str] = None,
                 stop_entity_id: Optional[str] = None):
        self.hass_url = hass_url.rstrip("/")
        self.token = token
        self.entity_id = entity_id
        self.start_entity_id = start_entity_id
        self.pause_entity_id = pause_entity_id
        self.resume_entity_id = resume_entity_id
        self.stop_entity_id = stop_entity_id
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.client: Optional[httpx.AsyncClient] = None
        self._player: Optional[MediaPlayer] = None

    @property
    def name(self) -> str:
        return "homeassistant"

    @classmethod
    def get_schema(cls) -> dict:
        return {
            "connection_fields": [
                {"name": "hass_url", "type": "string", "required": True, "label": "HA URL"},
                {"name": "token", "type": "password", "required": True, "label": "Access Token"}
            ],
            "entity_fields": [
                {"name": "entity_id", "type": "string", "required": True, "label": "Entity ID"}
            ]
        }

    @classmethod
    async def validate_connection(cls, config: dict) -> bool:
        """Test connection to HA."""
        hass_url = config.get("hass_url", "").rstrip("/")
        token = config.get("token", "")
        if not hass_url or not token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{hass_url}/api/",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return resp.status_code == 200 and "message" in resp.json() and resp.json()["message"] == "API running."
        except Exception as e:
            logger.error(f"HA validation failed: {e}")
            return False

    @classmethod
    async def validate_component(cls, config: dict) -> bool:
        """Test if HA entity exists."""
        hass_url = config.get("hass_url", "").rstrip("/")
        token = config.get("token", "")
        entity_id = config.get("entity_id", "")
        if not all([hass_url, token, entity_id]):
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{hass_url}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {token}"}
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"HA component validation failed for {entity_id}: {e}")
            return False

    @classmethod
    async def list_entities(cls, config: dict) -> list[dict]:
        """Fetch available camera and status entities from HA."""
        hass_url = config.get("hass_url", "").rstrip("/")
        token = config.get("token", "")
        if not hass_url or not token:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{hass_url}/api/states",
                    headers={"Authorization": f"Bearer {token}"}
                )
                resp.raise_for_status()
                states = resp.json()
                entities = []
                for state in states:
                    entity_id = state["entity_id"]
                    domain = entity_id.split(".")[0]
                    name = state.get("attributes", {}).get("friendly_name", entity_id)
                    
                    if domain == "camera":
                        entities.append({"id": entity_id, "name": name, "type": "camera"})
                    elif domain in ["sensor", "binary_sensor", "switch", "button"]:
                        if any(x in entity_id.lower() for x in ["status", "state", "print"]):
                            entities.append({"id": entity_id, "name": name, "type": "status"})
                        elif domain in ["button", "switch"]:
                            entities.append({"id": entity_id, "name": name, "type": "control"})
                return entities
        except Exception as e:
            logger.error(f"HA entity listing failed: {e}")
            return []

    async def _call_service(self, domain: str, service: str, service_data: dict) -> None:
        """Call a Home Assistant service."""
        if not self.client:
            await self.connect()
        try:
            response = await self.client.post(
                f"/api/services/{domain}/{service}",
                json=service_data
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to call HA service {domain}.{service}: {e}")

    async def _call_action(self, entity_id: Optional[str]) -> None:
        """Helper to call the appropriate service for an entity."""
        if not entity_id:
            return
        domain = entity_id.split(".")[0]
        service = "press" if domain == "button" else "turn_on"
        if "stop" in entity_id or "cancel" in entity_id:
            if domain == "switch":
                service = "turn_off"
        await self._call_service(domain, service, {"entity_id": entity_id})

    async def connect(self) -> None:
        """Initialize the HTTP client and test connection."""
        if not self.client:
            self.client = httpx.AsyncClient(base_url=self.hass_url, headers=self.headers)
        logger.info(f"Testing connection to HA at {self.hass_url} for entity {self.entity_id}")
        try:
            response = await self.client.get(f"/api/states/{self.entity_id}")
            response.raise_for_status()
            logger.info(f"Successfully connected to HA, entity {self.entity_id} state: {response.json().get('state')}")
            # Test camera snapshot proxy access (single JPEG)
            if self.entity_id.startswith("camera."):
                proxy_url = f"/api/camera_proxy/{self.entity_id}"
                logger.debug(f"Testing camera proxy access: {proxy_url}")
                test_resp = await self.client.get(proxy_url, timeout=10.0)
                if test_resp.status_code == 200:
                    content_type = test_resp.headers.get("Content-Type", "unknown")
                    logger.info(f"Camera proxy access verified. Content-Type: {content_type}")
                else:
                    logger.warning(f"Camera proxy access failed with status {test_resp.status_code}: {test_resp.text[:100]}")
        except Exception as e:
            logger.error(f"HA connection test failed: {e}")
            raise

    async def disconnect(self) -> None:
        """Close the HTTP client and any active media players."""
        if self._player:
            if hasattr(self._player, "stop"):
                self._player.stop()
            self._player = None
        if self.client:
            await self.client.aclose()
            self.client = None

    async def is_printing(self) -> bool:
        """Check if the printer is currently printing."""
        if not self.client:
            await self.connect()
        response = await self.client.get(f"/api/states/{self.entity_id}")
        response.raise_for_status()
        data = response.json()
        state = data.get("state", "").lower()
        return state in ["printing", "on", "active"] or self.entity_id.startswith("camera.")

    async def start(self) -> None:
        """Start/resume the print job."""
        await self._call_action(self.start_entity_id)

    async def pause(self) -> None:
        """Pause the current print."""
        await self._call_action(self.pause_entity_id)

    async def resume(self) -> None:
        """Resume the current print."""
        await self._call_action(self.resume_entity_id or self.start_entity_id)

    async def stop(self) -> None:
        """Cancel the current job."""
        await self._call_action(self.stop_entity_id)

    async def get_camera_track(self) -> Tuple[Optional[MediaStreamTrack], Optional[RTCPeerConnection]]:
        """Return a video track from Home Assistant's camera proxy."""
        if not self.client:
            await self.connect()
        if not self.entity_id.startswith("camera."):
            logger.warning(f"Entity {self.entity_id} is not a camera")
            return None, None
        stream_url = f"{self.hass_url}/api/camera_proxy_stream/{self.entity_id}"
        logger.info(f"Attempting to get camera track from {stream_url}")
        for fmt in ["mjpeg", None]:
            try:
                headers = f"Authorization: Bearer {self.token}"
                options = {
                    "headers": headers,
                    "fflags": "nobuffer",
                    "flags": "low_delay",
                    "probesize": "32",
                    "analyzeduration": "0",
                }
                if self.hass_url.startswith("https"):
                    options["tls_verify"] = "0"
                    options["verify_hostname"] = "0"
                logger.debug(f"Trying MediaPlayer with format={fmt} for {self.entity_id}")
                player = MediaPlayer(stream_url, format=fmt, options=options)
                if player.video:
                    try:
                        logger.debug(f"Verifying stream for {self.entity_id} (format={fmt})...")
                        await asyncio.wait_for(player.video.recv(), timeout=10.0)
                        logger.info(f"Successfully verified stream for {self.entity_id} with format={fmt}")
                        self._player = player
                        return self._player.video, None
                    except Exception as e:
                        logger.warning(f"Format {fmt} failed verification: {type(e).__name__} {e}")
                        if hasattr(player, "stop"): player.stop()
                        continue
            except Exception as e:
                logger.warning(f"Failed to create MediaPlayer with format {fmt}: {e}")
                continue
        logger.error(f"All stream formats failed for {self.entity_id}")
        return None, None
