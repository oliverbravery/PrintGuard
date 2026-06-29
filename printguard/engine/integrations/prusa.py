"""Prusa integration over PrusaLink's local HTTP API.

PrusaLink runs on the printer itself (MK4, MK4S, MK3.9, MK3.5, MINI, XL, CORE
One) or on a Raspberry Pi attached to an MK3/MK2.5. Its ``/api/v1`` API
authenticates with HTTP Digest — username ``maker`` and the PrusaLink password
shown on the printer. 
The client needs httpx, which the browser sandbox lacks, so it runs in hub mode only
(``browser_ok`` is False); the printer also sends no CORS headers.

PrusaConnect is deliberately not used: it routes through Prusa's cloud, whereas
PrintGuard keeps everything on hardware the user owns, and it exposes no
documented third-party control API.

API reference: https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml
pyprusalink (digest workaround): https://github.com/home-assistant-libs/pyprusalink
Printer-side setup (enabling PrusaLink, the password): https://help.prusa3d.com/guide/wi-fi-and-prusa-connect-link-setup-core-one-mk4-s-mk3-9-mk3-5-xl-mini_413293
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter

_USERNAME = "maker"
_TIMEOUT_S = 10.0

_STATUS_MAP = {
    "PRINTING": DeviceStatus.PRINTING,
    "PAUSED": DeviceStatus.PAUSED,
    "FINISHED": DeviceStatus.IDLE,
    "STOPPED": DeviceStatus.IDLE,
    "ERROR": DeviceStatus.ERROR,
}


class PrusaAdapter(IntegrationAdapter):
    """Talks to a Prusa printer's local PrusaLink API via pyprusalink."""

    id = "prusa"
    label = "Prusa (PrusaLink)"
    docs_url = "https://github.com/prusa3d/Prusa-Link-Web/blob/master/spec/openapi.yaml"
    setup_url = "https://help.prusa3d.com/guide/wi-fi-and-prusa-connect-link-setup-core-one-mk4-s-mk3-9-mk3-5-xl-mini_413293"
    setup_hint = (
        "Enable PrusaLink on the printer (Settings > Network > PrusaLink) and use the password "
        "shown there. The username is always 'maker'."
    )
    browser_ok = False
    experimental = True
    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.1.80",
            },
            "password": {
                "type": "string",
                "title": "PrusaLink password",
                "secret": True,
                "placeholder": "Settings > Network > PrusaLink",
            },
        },
        "required": ["base_url", "password"],
    }

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Reads the active job from /api/v1/job and normalises its state.

        No active job (HTTP 204) is idle; any failure to reach or authenticate
        with the printer is offline, which keeps inference watching. The HTTP
        function is unused — pyprusalink owns the digest-authenticated client.
        """
        try:
            job = await self._job(config)
        except Exception:
            return DeviceState(DeviceStatus.OFFLINE)
        if not job:
            return DeviceState(DeviceStatus.IDLE)
        file = job.get("file") or {}
        status = _STATUS_MAP.get(str(job.get("state", "")).upper(), DeviceStatus.UNKNOWN)
        return DeviceState(status, float(job.get("progress") or 0.0), file.get("display_name") or file.get("name"))

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Pauses, resumes or cancels the active job by its id."""
        job = await self._job(config)
        if not job:
            raise RuntimeError(f"Prusa printer has no active job to {action.value}")
        await self._command(config, int(job["id"]), action)

    async def _job(self, config: dict[str, Any]) -> dict[str, Any] | None:
        async with self._link(config) as link:
            job = await link.get_job()
        return dict(job) if job else None

    async def _command(self, config: dict[str, Any], job_id: int, action: DeviceAction) -> None:
        async with self._link(config) as link:
            if action is DeviceAction.PAUSE:
                await link.pause_job(job_id)
            elif action is DeviceAction.RESUME:
                await link.resume_job(job_id)
            else:
                await link.cancel_job(job_id)

    @asynccontextmanager
    async def _link(self, config: dict[str, Any]) -> AsyncIterator[Any]:
        import httpx
        from pyprusalink import PrusaLink

        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            yield PrusaLink(client, str(config["base_url"]).rstrip("/"), _USERNAME, str(config.get("password", "")))
