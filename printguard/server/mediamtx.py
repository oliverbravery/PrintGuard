"""Thin client for the MediaMTX control API and supervisor for a bundled binary.

API reference: https://bluenviron.github.io/mediamtx/
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..engine.cameras import webrtc_endpoint, whep_endpoint

logger = logging.getLogger(__name__)

READY_TIMEOUT_S = 10.0
RESTART_DELAY_S = 2.0
STOP_TIMEOUT_S = 5.0


def pull_source(url: str) -> str | None:
    """Returns the MediaMTX pull URL, or None when the hub reads it directly."""
    parts = urlsplit(url)
    if whep_endpoint(url):
        scheme = "wheps" if parts.scheme in ("https", "wheps") else "whep"
        return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))
    if webrtc_endpoint(url):
        raise ValueError("WebRTC source does not expose WHEP, use its WHEP, MJPEG or RTSP URL instead")
    if parts.scheme in ("http", "https"):
        return None
    return url


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
        payload: dict[str, Any] = {
            "source": source_url,
            "sourceOnDemand": True,
            "sourceOnDemandStartTimeout": "30s",
            "sourceOnDemandCloseAfter": "10s",
        }
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
    the failure logged, because dropped streams must never pass silently, and
    its lifetime is tied to the hub's so no exit can leave it holding the
    streaming ports.
    """

    def __init__(self, binary: str, config: str, api_base: str) -> None:
        self._binary = binary
        self._config = config
        self._api = urlsplit(api_base)
        self._process: asyncio.subprocess.Process | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = False
        self._watcher: subprocess.Popen[bytes] | None = None
        self._watch_fd = -1
        self._job: Any = None

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
            try:
                self._process = await asyncio.create_subprocess_exec(self._binary, self._config)
            except OSError as exc:
                logger.error("MediaMTX failed to launch (%s); retrying", exc)
                await asyncio.sleep(RESTART_DELAY_S)
                continue
            self._bind_lifetime(self._process.pid)
            code = await self._process.wait()
            self._release_lifetime()
            if self._stopping:
                return
            logger.error("MediaMTX exited (code %s); restarting", code)
            await asyncio.sleep(RESTART_DELAY_S)

    def _bind_lifetime(self, pid: int) -> None:
        """Makes the server die with this hub, however this hub exits.

        ``stop`` covers an orderly shutdown, but a hub that is force quit,
        killed or crashes never reaches it, and the orphan keeps the streaming
        ports for itself - blocking every hub, desktop app and container
        started on that host afterwards. Windows job objects end their members
        when the last handle closes; POSIX has no equivalent, so a shell reads
        one end of a pipe this process owns and kills the server the moment
        that pipe closes with it.
        """
        if os.name == "nt":
            import win32api
            import win32con
            import win32job

            if self._job is None:
                self._job = win32job.CreateJobObject(None, "")
                limits = win32job.QueryInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation)
                limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation, limits)
            handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
            win32job.AssignProcessToJobObject(self._job, handle)
            return
        read_fd, self._watch_fd = os.pipe()
        self._watcher = subprocess.Popen(["/bin/sh", "-c", f"read _; kill {pid} 2>/dev/null"], stdin=read_fd)
        os.close(read_fd)

    def _release_lifetime(self) -> None:
        """Drops the watcher for a server that has already exited."""
        if self._watcher is None:
            return
        self._watcher.terminate()
        self._watcher.wait()
        self._watcher = None
        os.close(self._watch_fd)

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
