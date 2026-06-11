"""OctoPrint integration.

API reference: https://docs.octoprint.org/en/master/api/
"""

from __future__ import annotations

from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter

_STATUS_MAP = {
    "printing": DeviceStatus.PRINTING,
    "resuming": DeviceStatus.PRINTING,
    "paused": DeviceStatus.PAUSED,
    "pausing": DeviceStatus.PAUSED,
    "operational": DeviceStatus.IDLE,
    "cancelling": DeviceStatus.IDLE,
    "offline": DeviceStatus.OFFLINE,
    "error": DeviceStatus.ERROR,
}


class OctoPrintAdapter(IntegrationAdapter):
    """Talks to OctoPrint's REST API using an application API key."""

    id = "octoprint"
    label = "OctoPrint"
    docs_url = "https://docs.octoprint.org/en/master/api/"
    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.1.50:5000",
            },
            "api_key": {"type": "string", "title": "API key", "secret": True, "placeholder": "OctoPrint application key"},
        },
        "required": ["base_url", "api_key"],
    }

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        return {"X-Api-Key": str(config.get("api_key", ""))}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Reads /api/job and normalises OctoPrint's state text."""
        status, body = await http("GET", f"{config['base_url'].rstrip('/')}/api/job", headers=self._headers(config))
        if status != 200 or not isinstance(body, dict):
            return DeviceState(DeviceStatus.OFFLINE)
        text = str(body.get("state", "")).lower()
        matched = next((s for key, s in _STATUS_MAP.items() if text.startswith(key)), DeviceStatus.UNKNOWN)
        progress = float((body.get("progress") or {}).get("completion") or 0.0)
        job = ((body.get("job") or {}).get("file") or {}).get("name")
        return DeviceState(matched, progress, job)

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Issues pause/resume/cancel through /api/job."""
        payload = (
            {"command": "cancel"}
            if action is DeviceAction.CANCEL
            else {"command": "pause", "action": action.value}
        )
        status, _ = await http(
            "POST",
            f"{config['base_url'].rstrip('/')}/api/job",
            headers=self._headers(config),
            json=payload,
        )
        if status >= 400:
            raise RuntimeError(f"OctoPrint rejected {action.value}: HTTP {status}")
