"""Thin client for the MediaMTX control API and supervisor for a bundled binary.

API reference: https://bluenviron.github.io/mediamtx/
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

READY_TIMEOUT_S = 10.0
RESTART_DELAY_S = 2.0
STOP_TIMEOUT_S = 5.0


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


class EmbeddedMediaMTX:
    """Supervises a MediaMTX binary bundled into the hub image.

    The hub ships the streaming server inside its own image and runs it as a
    child process, so a single container is the whole deployment instead of a
    second image whose version may be unavailable on a given host. It starts
    only when the image provides a binary path; pointed at an external MediaMTX
    the hub uses that and this never runs. A server that exits is restarted and
    the failure logged, because dropped streams must never pass silently.
    """

    def __init__(self, binary: str, config: str, api_base: str) -> None:
        self._binary = binary
        self._config = config
        self._api = urlsplit(api_base)
        self._process: asyncio.subprocess.Process | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        """Launches the server and waits until its control API accepts connections."""
        self._supervisor = asyncio.ensure_future(self._run())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + READY_TIMEOUT_S
        while loop.time() < deadline:
            if await self._listening():
                return
            await asyncio.sleep(0.2)
        logger.error("MediaMTX did not accept connections within %ss", READY_TIMEOUT_S)

    async def _run(self) -> None:
        while not self._stopping:
            self._process = await asyncio.create_subprocess_exec(self._binary, self._config)
            code = await self._process.wait()
            if self._stopping:
                return
            logger.error("MediaMTX exited (code %s); restarting", code)
            await asyncio.sleep(RESTART_DELAY_S)

    async def _listening(self) -> bool:
        try:
            _, writer = await asyncio.open_connection(self._api.hostname, self._api.port)
        except OSError:
            return False
        writer.close()
        return True

    async def stop(self) -> None:
        """Stops supervising and terminates the server."""
        self._stopping = True
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._process.kill()
        if self._supervisor is not None:
            await self._supervisor
