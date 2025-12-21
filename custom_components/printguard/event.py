"""Support for PrintGuard event entities."""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .base import PrintGuardEntity
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PrintGuard events."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    async_add_entities(
        PrintGuardDefectEvent(coordinator, p_id, p_data["info"]["name"])
        for p_id, p_data in coordinator.data.items()
    )


class PrintGuardDefectEvent(PrintGuardEntity, EventEntity):
    """Event entity for PrintGuard defect detection."""

    _attr_device_class = EventDeviceClass.MOTION
    _attr_event_types = ["defect_detected", "normal"]
    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator, p_id, p_name) -> None:
        """Initialize."""
        super().__init__(coordinator, p_id, p_name)
        self._attr_name = "Detection"
        self._attr_unique_id = f"{DOMAIN}_{p_id}_detection_event"

    async def async_added_to_hass(self) -> None:
        """Register dispatcher."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._printer_id}_event",
                self.trigger_defect_event,
            )
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return attributes."""
        if not self.printer_data or not (pred := self.printer_data["prediction"]):
            return {}
        return {
            "last_detection_class": pred.get("class_name"),
            "last_confidence": pred.get("confidence"),
        }

    @callback
    def trigger_defect_event(self, class_name: str, confidence: float, session_id: str | None) -> None:
        """Trigger event."""
        event_type = "defect_detected" if class_name.lower() != "normal" else "normal"
        self._trigger_event(
            event_type,
            {
                "class": class_name,
                "confidence": confidence,
                "session_id": session_id,
            },
        )
        self.async_write_ha_state()
