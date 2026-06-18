"""Klipper integration via the Moonraker API.

API reference: https://moonraker.readthedocs.io/en/latest/external_api/introduction/
Authorization and CORS (trusted_clients, cors_domains): https://moonraker.readthedocs.io/en/latest/configuration/#authorization
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

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
    docs_url = "https://moonraker.readthedocs.io/en/latest/external_api/introduction/"
    setup_url = "https://moonraker.readthedocs.io/en/latest/configuration/#authorization"
    setup_hint = (
        "On a trusted LAN Moonraker needs no key. In local mode, add PrintGuard's origin "
        "to cors_domains in the [authorization] section of moonraker.conf."
    )
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

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Lists Moonraker's registered webcams via /server/webcams/list.

        Each webcam's stream_url may be relative to the Moonraker host and is
        resolved against it; its stable uid keys the registered camera.
        """
        status, body = await http("GET", f"{config['base_url'].rstrip('/')}/server/webcams/list", headers=self._headers(config))
        if status != 200 or not isinstance(body, dict):
            return []
        found: list[dict[str, Any]] = []
        for webcam in (body.get("result") or {}).get("webcams") or []:
            if not webcam.get("enabled", True) or not webcam.get("stream_url"):
                continue
            found.append(
                {
                    "key": str(webcam.get("uid") or webcam.get("name") or len(found)),
                    "name": webcam.get("name") or "Webcam",
                    "source": {"kind": "url", "url": urljoin(config["base_url"], webcam["stream_url"])},
                }
            )
        return found
