"""Support for PrintGuard button entities."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up PrintGuard buttons."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    async_add_entities([PrintGuardRefreshButton(coordinator)])


class PrintGuardRefreshButton(ButtonEntity):
    """Button to refresh PrintGuard data."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        self.coordinator = coordinator
        self._attr_name = "Refresh"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.entry.entry_id}_refresh"

    async def async_press(self) -> None:
        """Refresh data."""
        await self.coordinator.async_request_refresh()
