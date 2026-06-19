"""OctoPrint integration.

API reference: https://docs.octoprint.org/en/master/api/
Application keys (how the API key is obtained): https://docs.octoprint.org/en/master/bundledplugins/appkeys.html
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

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
    setup_url = "https://docs.octoprint.org/en/master/bundledplugins/appkeys.html"
    setup_hint = (
        "Copy an application key from OctoPrint under Settings > Application Keys. "
        "In local mode, also enable CORS under Settings > API."
    )
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

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Reads the configured webcam stream from /api/settings.

        OctoPrint 1.9 moved the stream URL into the bundled Classic Webcam
        plugin and deprecated ``webcam.streamUrl``, so the plugin location is
        preferred and the legacy field is the fallback. The URL may be relative
        to the OctoPrint host and is resolved against it.
        """
        status, body = await http("GET", f"{config['base_url'].rstrip('/')}/api/settings", headers=self._headers(config))
        if status != 200 or not isinstance(body, dict):
            return []
        stream = ((body.get("plugins") or {}).get("classicwebcam") or {}).get("stream") or (body.get("webcam") or {}).get("streamUrl")
        if not stream:
            return []
        return [{"key": "webcam", "name": "OctoPrint webcam", "source": {"kind": "url", "url": urljoin(config["base_url"], stream)}}]
