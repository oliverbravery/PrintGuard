"""Base entity for PrintGuard."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PrintGuardDataUpdateCoordinator


class PrintGuardEntity(CoordinatorEntity[PrintGuardDataUpdateCoordinator]):
    """Base entity for PrintGuard."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PrintGuardDataUpdateCoordinator,
        printer_id: str,
        printer_name: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._printer_id = printer_id
        self._printer_name = printer_name

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._printer_id)},
            name=f"PrintGuard {self._printer_name}",
            manufacturer="PrintGuard",
            model="Monitored Printer",
            via_device=(DOMAIN, self.coordinator.entry.entry_id),
        )

    @property
    def printer_data(self) -> dict | None:
        """Return printer data from coordinator."""
        return self.coordinator.data.get(self._printer_id)

