"""Klipper integration via the Moonraker API.

API reference: https://moonraker.readthedocs.io/en/latest/web_api/
"""

from __future__ import annotations

from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter

_STATUS_MAP = {
    "printing": DeviceStatus.PRINTING,
    "paused": DeviceStatus.PAUSED,
    "standby": DeviceStatus.IDLE,
    "complete": DeviceStatus.IDLE,
    "cancelled": DeviceStatus.IDLE,
    "error": DeviceStatus.ERROR,
}


class KlipperAdapter(IntegrationAdapter):
    """Talks to Moonraker's HTTP API, optionally with an API key."""

    id = "klipper"
    label = "Klipper (Moonraker)"
    docs_url = "https://moonraker.readthedocs.io/en/latest/web_api/"
    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.1.60:7125",
            },
            "api_key": {"type": "string", "title": "API key (optional)", "secret": True, "placeholder": "Leave blank if unset"},
        },
        "required": ["base_url"],
    }

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = str(config.get("api_key") or "")
        return {"X-Api-Key": key} if key else {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Queries print_stats and virtual_sdcard for state and progress."""
        url = f"{config['base_url'].rstrip('/')}/printer/objects/query?print_stats&virtual_sdcard"
        status, body = await http("GET", url, headers=self._headers(config))
        if status != 200 or not isinstance(body, dict):
            return DeviceState(DeviceStatus.OFFLINE)
        objects = (body.get("result") or {}).get("status") or {}
        stats = objects.get("print_stats") or {}
        matched = _STATUS_MAP.get(str(stats.get("state", "")).lower(), DeviceStatus.UNKNOWN)
        progress = float((objects.get("virtual_sdcard") or {}).get("progress") or 0.0) * 100.0
        return DeviceState(matched, progress, stats.get("filename") or None)

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Issues pause/resume/cancel through /printer/print endpoints."""
        status, _ = await http(
            "POST",
            f"{config['base_url'].rstrip('/')}/printer/print/{action.value}",
            headers=self._headers(config),
        )
        if status >= 400:
            raise RuntimeError(f"Moonraker rejected {action.value}: HTTP {status}")
