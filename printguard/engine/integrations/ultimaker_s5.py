"""Read-only status integration for the Ultimaker S5 local API."""

from __future__ import annotations

from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter


class UltimakerS5Adapter(IntegrationAdapter):
    """Reads printer status without sending commands to the printer."""

    id = "ultimaker_s5"
    label = "Ultimaker S5 (status only)"
    setup_hint = (
        "No authentication is required. The printer API uses HTTP; "
        "use this integration only on a trusted LAN."
    )
    docs_url = ""
    experimental = True

    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.68.104",
            },
        },
        "required": ["base_url"],
    }

    _STATUS_MAP = {
        "printing": DeviceStatus.PRINTING,
        "idle": DeviceStatus.IDLE,
        "error": DeviceStatus.ERROR,
    }

    async def fetch_state(
        self, http: HttpFn, config: dict[str, Any]
    ) -> DeviceState:
        base_url = str(config["base_url"]).rstrip("/")
        status, body = await http(
            "GET", f"{base_url}/api/v1/printer/status"
        )

        if status != 200:
            raise RuntimeError(
                f"Ultimaker S5 status request failed: HTTP {status}"
            )

        if not isinstance(body, str):
            raise RuntimeError(
                "Ultimaker S5 returned an unexpected status response"
            )

        value = body.strip().lower()
        if value not in {
            "booting",
            "waiting_for_peripherals",
            "idle",
            "printing",
            "error",
            "maintenance",
        }:
            raise RuntimeError(
                f"Ultimaker S5 returned an unknown printer status: {value!r}"
            )

        return DeviceState(
            self._STATUS_MAP.get(value, DeviceStatus.UNKNOWN)
        )

    async def send(
        self,
        http: HttpFn,
        config: dict[str, Any],
        action: DeviceAction,
    ) -> None:
        raise RuntimeError(
            "Ultimaker S5 integration is read-only; printer commands "
            "are not supported"
        )
