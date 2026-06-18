"""Thin client for the MediaMTX control API.

API reference: https://bluenviron.github.io/mediamtx/
"""

from __future__ import annotations

from typing import Any

import httpx


class MediaMTX:
    """Manages stream paths on a MediaMTX instance."""

    def __init__(self, api_base: str, rtsp_base: str, client: httpx.AsyncClient) -> None:
        self._api = api_base.rstrip("/")
        self._rtsp = rtsp_base.rstrip("/")
        self._client = client

    def rtsp_url(self, path: str) -> str:
        """Internal RTSP URL the server reads frames from."""
        return f"{self._rtsp}/{path}"

    async def list_paths(self) -> list[str]:
        """Names of currently active stream paths."""
        resp = await self._client.get(f"{self._api}/v3/paths/list", timeout=5.0)
        resp.raise_for_status()
        return [item["name"] for item in resp.json().get("items", [])]

    async def ensure_path(self, name: str, source_url: str, fingerprint: str | None = None) -> None:
        """Creates or updates a path that pulls from an external URL.

        A fingerprint is the SHA-256 of a self-signed source certificate (hex,
        no colons), letting MediaMTX validate an otherwise-untrusted RTSPS feed.
        """
        payload: dict[str, Any] = {"source": source_url, "sourceOnDemand": False}
        if fingerprint:
            payload["sourceFingerprint"] = fingerprint
        resp = await self._client.post(f"{self._api}/v3/config/paths/add/{name}", json=payload, timeout=5.0)
        if resp.status_code == 400:
            resp = await self._client.patch(f"{self._api}/v3/config/paths/patch/{name}", json=payload, timeout=5.0)
        resp.raise_for_status()

    async def remove_path(self, name: str) -> None:
        """Deletes a managed path, ignoring paths that no longer exist."""
        await self._client.delete(f"{self._api}/v3/config/paths/delete/{name}", timeout=5.0)
