"""The PrintGuard integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .api import PrintGuardApiClient
from .const import (
    CONF_CAMERA,
    CONF_CLIENT_PRIVATE_KEY,
    CONF_CLIENT_PUBLIC_KEY,
    CONF_PAUSE_ENTITY,
    CONF_PRINTER_NAME,
    CONF_PRINTERS,
    CONF_RESUME_ENTITY,
    CONF_SERVER_PUBLIC_KEY,
    CONF_START_ENTITY,
    CONF_STOP_ENTITY,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import PrintGuardDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PrintGuard from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    api_client = PrintGuardApiClient(
        hass,
        entry.data[CONF_URL],
        entry.data.get(CONF_SERVER_PUBLIC_KEY),
        entry.data.get(CONF_CLIENT_PRIVATE_KEY),
        entry.data.get(CONF_CLIENT_PUBLIC_KEY),
    )
    try:
        latest_server_key = await api_client.fetch_server_public_key()
        if latest_server_key and latest_server_key != entry.data.get(CONF_SERVER_PUBLIC_KEY):
            new_data = dict(entry.data)
            new_data[CONF_SERVER_PUBLIC_KEY] = latest_server_key
            hass.config_entries.async_update_entry(entry, data=new_data)
            api_client._server_pub_key = latest_server_key
    except Exception as err:
        _LOGGER.debug("Could not refresh server public key at startup: %s", err)
    coordinator = PrintGuardDataUpdateCoordinator(hass, entry, api_client)
    stored_printers = entry.options.get(CONF_PRINTERS, []) or entry.data.get(CONF_PRINTERS, [])
    token = entry.data.get(CONF_TOKEN)
    for printer in stored_printers:
        try:
            await api_client.register_printer(hass, token, printer)
        except Exception as err:
            _LOGGER.warning("Failed to re-register printer %s: %s", printer.get(CONF_PRINTER_NAME), err)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
