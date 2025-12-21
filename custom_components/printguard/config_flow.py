"""Config flow for PrintGuard integration."""
from __future__ import annotations

import base64
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CannotConnect,
    InvalidPrinterConfig,
    PrinterAlreadyExists,
    PrintGuardApiClient,
)
from .const import (
    CONF_CAMERA,
    CONF_CLIENT_PRIVATE_KEY,
    CONF_CLIENT_PUBLIC_KEY,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_NOTIFY_SERVICE,
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
)
from .crypto import CryptoHandler

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default="http://localhost:8000"): str,
        vol.Required(CONF_TOKEN): str,
    }
)


def get_add_printer_schema(_hass: HomeAssistant) -> vol.Schema:
    """Get the schema for adding a printer."""
    return vol.Schema(
        {
            vol.Required(CONF_PRINTER_NAME): str,
            vol.Required(CONF_CAMERA): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="camera")
            ),
            vol.Optional(CONF_START_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
            vol.Optional(CONF_PAUSE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
            vol.Optional(CONF_RESUME_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
            vol.Optional(CONF_STOP_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig()
            ),
        }
    )


async def _fetch_server_public_key(hass: HomeAssistant, url: str) -> str:
    """Fetch server public key from the PrintGuard server."""
    session = async_get_clientsession(hass)
    async with session.get(f"{url}/api/crypto/key", timeout=10) as response:
        response.raise_for_status()
        payload = await response.json()
        public_key = payload.get("public_key")
        if not public_key:
            raise HomeAssistantError("Missing 'public_key' in server response")
        return public_key


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    url = data[CONF_URL].rstrip("/")
    try:
        session = async_get_clientsession(hass)
        async with session.get(f"{url}/api/health", timeout=10) as response:
            response.raise_for_status()
        await _fetch_server_public_key(hass, url)
    except Exception as err:
        raise CannotConnect(str(err)) from err
    return {"title": "PrintGuard"}


def _build_api_client(hass: HomeAssistant, data: dict[str, Any]) -> PrintGuardApiClient:
    """Build an API client from entry/config-flow data."""
    url = data[CONF_URL].rstrip("/")
    return PrintGuardApiClient(
        hass,
        url,
        data.get(CONF_SERVER_PUBLIC_KEY),
        data.get(CONF_CLIENT_PRIVATE_KEY),
        data.get(CONF_CLIENT_PUBLIC_KEY),
    )


async def _register_printer_with_errors(
    hass: HomeAssistant,
    api_client: PrintGuardApiClient,
    token: str | None,
    printer_input: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Register printer and return (printer, error_key)."""
    try:
        registered_printer = await api_client.register_printer(hass, token, printer_input)
        return registered_printer, None
    except CannotConnect:
        return None, "cannot_connect"
    except PrinterAlreadyExists:
        return None, "printer_already_exists"
    except InvalidPrinterConfig as err:
        _LOGGER.error("Invalid printer config: %s", err)
        return None, "invalid_config"
    except Exception:
        _LOGGER.exception("Unexpected exception while adding printer")
        return None, "unknown"

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PrintGuard."""
    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._base_data: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = user_input[CONF_URL].rstrip("/")
                user_input[CONF_SERVER_PUBLIC_KEY] = await _fetch_server_public_key(
                    self.hass, url
                )
                handler = CryptoHandler()
                user_input[CONF_CLIENT_PRIVATE_KEY] = base64.b64encode(
                    handler.get_private_key_bytes()
                ).decode("utf-8")
                user_input[CONF_CLIENT_PUBLIC_KEY] = handler.get_public_key_b64()
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                self._base_data = user_input
                return await self.async_step_printer()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle selecting the printer camera and controls."""
        errors: dict[str, str] = {}
        if not self._base_data:
            return await self.async_step_user()
        if user_input is not None:
            token = self._base_data.get(CONF_TOKEN)
            api_client = _build_api_client(self.hass, self._base_data)
            registered_printer, err_key = await _register_printer_with_errors(
                self.hass, api_client, token, user_input
            )
            if err_key:
                errors["base"] = err_key
            else:
                data = dict(self._base_data)
                data[CONF_PRINTERS] = [registered_printer]
                return self.async_create_entry(title="PrintGuard", data=data)
        return self.async_show_form(
            step_id="printer",
            data_schema=get_add_printer_schema(self.hass),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for PrintGuard."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._printer_to_remove: str | None = None

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - show menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_printer", "manage_printers", "notifications"],
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle notification settings."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_ENABLE_NOTIFICATIONS] = user_input.get(
                CONF_ENABLE_NOTIFICATIONS, False
            )
            options[CONF_NOTIFY_SERVICE] = user_input.get(CONF_NOTIFY_SERVICE, "")
            return self.async_create_entry(title="", data=options)
        notify_services = [
            f"notify.{service}"
            for service in self.hass.services.async_services().get("notify", {})
        ]
        current_enabled = self.config_entry.options.get(
            CONF_ENABLE_NOTIFICATIONS, False
        )
        current_service = self.config_entry.options.get(CONF_NOTIFY_SERVICE, "")
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLE_NOTIFICATIONS, default=current_enabled
                ): bool,
                vol.Optional(CONF_NOTIFY_SERVICE, default=current_service): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=notify_services,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    )
                    if notify_services
                    else str
                ),
            }
        )

        return self.async_show_form(step_id="notifications", data_schema=schema)

    async def async_step_add_printer(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new printer."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = self.config_entry.data.get(CONF_TOKEN)
            api_client = _build_api_client(self.hass, self.config_entry.data)
            registered_printer, err_key = await _register_printer_with_errors(
                self.hass, api_client, token, user_input
            )
            if registered_printer:
                options = dict(self.config_entry.options)
                printers = list(options.get(CONF_PRINTERS, []))
                printers.append(registered_printer)
                options[CONF_PRINTERS] = printers
                return self.async_create_entry(title="", data=options)
            if err_key:
                errors["base"] = err_key
        return self.async_show_form(
            step_id="add_printer",
            data_schema=get_add_printer_schema(self.hass),
            errors=errors,
        )

    async def async_step_manage_printers(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle managing existing printers."""
        printers = self.config_entry.options.get(CONF_PRINTERS, [])
        if not printers:
            return self.async_abort(reason="no_printers")
        if user_input is not None:
            selected = user_input.get("printer")
            if selected:
                self._printer_to_remove = selected
                return await self.async_step_confirm_remove()
        printer_options = {
            p["printer_id"]: f"{p[CONF_PRINTER_NAME]} ({p[CONF_CAMERA]})"
            for p in printers
        }
        return self.async_show_form(
            step_id="manage_printers",
            data_schema=vol.Schema(
                {vol.Required("printer"): vol.In(printer_options)}
            ),
        )

    async def async_step_confirm_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm printer removal."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            printers = [
                p
                for p in options.get(CONF_PRINTERS, [])
                if p["printer_id"] != self._printer_to_remove
            ]
            options[CONF_PRINTERS] = printers
            url = self.config_entry.data[CONF_URL].rstrip("/")
            api_client = PrintGuardApiClient(
                self.hass,
                url,
                self.config_entry.data.get(CONF_SERVER_PUBLIC_KEY),
                self.config_entry.data.get(CONF_CLIENT_PRIVATE_KEY),
                self.config_entry.data.get(CONF_CLIENT_PUBLIC_KEY),
            )
            await api_client.delete_printer(self._printer_to_remove)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="confirm_remove",
            description_placeholders={"printer_id": self._printer_to_remove},
        )
