"""Support for PrintGuard sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import PrintGuardEntity
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PrintGuard sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    entities: list[SensorEntity] = [
        PrintGuardConnectionSensor(coordinator),
    ]
    for p_id, p_data in coordinator.data.items():
        entities.append(
            PrintGuardPrinterSensor(coordinator, p_id, p_data["info"]["name"])
        )
    async_add_entities(entities)


class PrintGuardConnectionSensor(SensorEntity):
    """Sensor showing PrintGuard server connection status."""
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["connected", "error"]
    _attr_icon = "mdi:server-network"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        self.coordinator = coordinator
        self._attr_name = "Connection Status"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.entry.entry_id}_connection"

    @property
    def device_info(self) -> DeviceInfo:
        """Create the PrintGuard Server device.

        Other entities reference this via `via_device`, so it must exist.
        """
        url = getattr(getattr(self.coordinator, "api_client", None), "_url", None)
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            name="PrintGuard Server",
            manufacturer="PrintGuard",
            model="Print Failure Detection",
            configuration_url=url,
        )

    @property
    def native_value(self) -> str:
        """Return status."""
        return "connected" if self.coordinator.last_update_success else "error"


class PrintGuardPrinterSensor(PrintGuardEntity, SensorEntity):
    """Representation of a PrintGuard printer status sensor."""

    _attr_icon = "mdi:printer-3d"

    def __init__(self, coordinator, p_id, p_name) -> None:
        """Initialize."""
        super().__init__(coordinator, p_id, p_name)
        self._attr_name = f"{p_name} Status"
        self._attr_unique_id = f"{DOMAIN}_{p_id}_status"

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self.printer_data:
            return "unknown"
        return self.printer_data["info"].get("status", "idle")

    @property
    def extra_state_attributes(self) -> dict:
        """Return attributes."""
        if not self.printer_data:
            return {}
        return {
            "provider": self.printer_data["info"].get("provider"),
            "linked_session_id": self.printer_data["info"].get("linked_session_id"),
        }
