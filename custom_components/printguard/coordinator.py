"""DataUpdateCoordinator for PrintGuard."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import PrintGuardApiClient
from .const import (
    CONF_ENABLE_NOTIFICATIONS,
    CONF_NOTIFY_SERVICE,
    CONF_PRINTER_NAME,
    DOMAIN,
    EVENT_DEFECT_DETECTED,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class PrintGuardDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching PrintGuard data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api_client: PrintGuardApiClient,
    ) -> None:
        """Initialize the coordinator."""
        self.api_client = api_client
        self.entry = entry
        self._last_defect_states: dict[str, str] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from PrintGuard."""
        try:
            printers = await self.api_client.get_printers()
            new_data: dict[str, Any] = {}
            for printer in printers:
                p_id = printer["printer_id"]
                full_info = await self.api_client.get_printer(p_id)
                prediction = None
                if full_info and (session_id := full_info.get("linked_session_id")):
                    prediction = await self.api_client.get_prediction_result(session_id)
                new_data[p_id] = {
                    "info": full_info or printer,
                    "prediction": prediction
                }
                await self._check_changes(p_id, new_data[p_id])

            return new_data
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _check_changes(self, printer_id: str, data: dict[str, Any]) -> None:
        """Detect status changes and trigger events/notifications."""
        prediction = data.get("prediction")
        if not prediction or prediction.get("status") != "success":
            return
        class_name = prediction.get("class_name")
        if not class_name:
            return
        last_class = self._last_defect_states.get(printer_id)
        if class_name == last_class:
            return
        self._last_defect_states[printer_id] = class_name
        
        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_{printer_id}_event",
            class_name,
            prediction.get("confidence", 0),
            data["info"].get("linked_session_id")
        )
        if class_name.lower() == "normal":
            return
        printer_name = data["info"].get(CONF_PRINTER_NAME, printer_id)
        confidence = prediction.get("confidence", 0)
        session_id = data["info"].get("linked_session_id")
        self.hass.bus.async_fire(
            EVENT_DEFECT_DETECTED,
            {
                "printer_id": printer_id,
                "printer_name": printer_name,
                "class": class_name,
                "confidence": confidence,
                "session_id": session_id,
            },
        )
        if self.entry.options.get(CONF_ENABLE_NOTIFICATIONS):
            service = self.entry.options.get(CONF_NOTIFY_SERVICE)
            if service:
                await self._send_notification(
                    service,
                    f"Print Error Detected: {printer_name}",
                    f"Detected {class_name} with {confidence:.0%} confidence",
                )

    async def _send_notification(self, service: str, title: str, message: str) -> None:
        """Send a notification via the configured service."""
        try:
            domain, service_name = service.split(".", 1) if "." in service else ("notify", service)
            await self.hass.services.async_call(
                domain, service_name, {"title": title, "message": message}
            )
        except Exception as err:
            _LOGGER.error("Failed to send notification: %s", err)

