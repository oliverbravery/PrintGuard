"""Support for PrintGuard camera entities."""
from __future__ import annotations

import logging
from typing import Any
import uuid

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import PrintGuardEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_WEB_RTC_FEATURE: CameraEntityFeature = getattr(
    CameraEntityFeature, "WEB_RTC", CameraEntityFeature(0)
)

try:
    from homeassistant.components.camera import WebRTCAnswer
except Exception:
    WebRTCAnswer = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PrintGuard cameras."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities(
        PrintGuardCamera(coordinator, p_id, p_data["info"]["name"])
        for p_id, p_data in coordinator.data.items()
    )


class PrintGuardCamera(PrintGuardEntity, Camera):
    """Camera entity for PrintGuard stream."""

    _attr_supported_features = _WEB_RTC_FEATURE

    def __init__(self, coordinator, p_id, p_name) -> None:
        """Initialize."""
        super().__init__(coordinator, p_id, p_name)
        Camera.__init__(self)
        self._attr_name = "Camera"
        self._attr_unique_id = f"{DOMAIN}_{p_id}_camera"
        self._session_id_override: str | None = None

    def _get_session_id(self) -> str | None:
        """Get linked session id (override first, then coordinator data)."""
        if self._session_id_override:
            return self._session_id_override
        if not self.printer_data:
            return None
        return self.printer_data["info"].get("linked_session_id")

    async def _ensure_stream_session(self) -> str | None:
        """Ensure the server has an active stream session for this printer."""
        if (session_id := self._get_session_id()):
            return session_id
        new_session_id = uuid.uuid4().hex
        _LOGGER.debug(
            "No linked_session_id; starting printer stream printer_id=%s new_session_id=%s",
            self._printer_id,
            new_session_id,
        )
        try:
            started_session_id = await self.coordinator.api_client.start_printer_stream(
                self._printer_id, new_session_id
            )
        except Exception as err:
            _LOGGER.debug(
                "Failed starting printer stream (will appear disconnected): printer_id=%s err=%s",
                self._printer_id,
                err,
            )
            return None
        if started_session_id:
            self._session_id_override = started_session_id
            await self.coordinator.async_request_refresh()
            return started_session_id
        return None

    @property
    def is_streaming(self) -> bool:
        """Return true if streaming."""
        return self._get_session_id() is not None

    @property
    def extra_state_attributes(self) -> dict:
        """Return attributes."""
        if not self.printer_data:
            return {}
        session_id = self._get_session_id()
        return {
            "printer_id": self._printer_id,
            "session_id": session_id,
        }

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        """Return a still image."""
        session_id = await self._ensure_stream_session()
        if not session_id:
            return None
        _LOGGER.debug("Fetching snapshot for printer_id=%s session_id=%s", self._printer_id, session_id)
        try:
            image = await self.coordinator.api_client.get_snapshot(session_id)
        except Exception as err:
            _LOGGER.debug(
                "Snapshot fetch failed (will appear disconnected): printer_id=%s session_id=%s err=%s",
                self._printer_id,
                session_id,
                err,
            )
            return None
        if image is None:
            self._session_id_override = None
            session_id = await self._ensure_stream_session()
            if session_id:
                _LOGGER.debug(
                    "Retrying snapshot after starting new session printer_id=%s session_id=%s",
                    self._printer_id,
                    session_id,
                )
                try:
                    image = await self.coordinator.api_client.get_snapshot(session_id)
                except Exception as err:
                    _LOGGER.debug(
                        "Snapshot retry failed: printer_id=%s session_id=%s err=%s",
                        self._printer_id,
                        session_id,
                        err,
                    )
                    return None
        return image

    async def async_handle_web_rtc_offer(self, offer: Any) -> Any:
        """Handle WebRTC offer (supports multiple HA API shapes)."""
        session_id = await self._ensure_stream_session()
        if not session_id:
            return None
        if isinstance(offer, str):
            offer_sdp = offer
        else:
            offer_sdp = getattr(offer, "sdp", None) or (offer.get("sdp") if isinstance(offer, dict) else None)
        if not offer_sdp:
            _LOGGER.error("WebRTC offer missing SDP for printer_id=%s session_id=%s (offer=%s)", self._printer_id, session_id, offer)
            return None
        _LOGGER.debug("Sending WebRTC offer for printer_id=%s session_id=%s", self._printer_id, session_id)
        try:
            answer_sdp = await self.coordinator.api_client.send_webrtc_offer(session_id, offer_sdp)
        except Exception as err:
            _LOGGER.debug(
                "WebRTC offer failed (will appear disconnected): printer_id=%s session_id=%s err=%s",
                self._printer_id,
                session_id,
                err,
            )
            return None
        if not answer_sdp:
            _LOGGER.debug("WebRTC answer missing; retrying with new session printer_id=%s", self._printer_id)
            self._session_id_override = None
            session_id = await self._ensure_stream_session()
            if not session_id:
                _LOGGER.error(
                    "WebRTC answer missing/empty and could not start new session printer_id=%s",
                    self._printer_id,
                )
                return None
            try:
                answer_sdp = await self.coordinator.api_client.send_webrtc_offer(session_id, offer_sdp)
            except Exception as err:
                _LOGGER.debug(
                    "WebRTC offer retry failed: printer_id=%s session_id=%s err=%s",
                    self._printer_id,
                    session_id,
                    err,
                )
                return None
            if not answer_sdp:
                _LOGGER.error(
                    "WebRTC answer missing/empty for printer_id=%s session_id=%s",
                    self._printer_id,
                    session_id,
                )
                return None
        if WebRTCAnswer is not None:
            return WebRTCAnswer(sdp=answer_sdp, type="answer")
        return answer_sdp
