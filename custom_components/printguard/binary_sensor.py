"""Support for PrintGuard binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import PrintGuardEntity
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PrintGuard binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities(
        PrintGuardDefectBinarySensor(coordinator, p_id, p_data["info"]["name"])
        for p_id, p_data in coordinator.data.items()
    )


class PrintGuardDefectBinarySensor(PrintGuardEntity, BinarySensorEntity):
    """Binary sensor for PrintGuard defect detection."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, p_id, p_name) -> None:
        """Initialize."""
        super().__init__(coordinator, p_id, p_name)
        self._attr_name = "Defect Detected"
        self._attr_unique_id = f"{DOMAIN}_{p_id}_defect"

    @property
    def is_on(self) -> bool:
        """Return true if defect is detected."""
        if not self.printer_data or not (pred := self.printer_data["prediction"]):
            return False
        return pred.get("class_name", "").lower() != "normal"
