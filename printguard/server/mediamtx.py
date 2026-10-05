"""Thin client for the MediaMTX control API and supervisor for a bundled binary.

API reference: https://bluenviron.github.io/mediamtx/
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..engine.cameras import webrtc_endpoint, whep_endpoint

logger = logging.getLogger(__name__)

READY_TIMEOUT_S = 10.0
RESTART_DELAY_S = 2.0
STOP_TIMEOUT_S = 5.0
API_USER_ENV = "MTX_AUTHINTERNALUSERS_1"


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
    """Manages stream paths on a MediaMTX instance.

    A path added through the control API lives in the server's memory, so the
    ones this hub added are remembered here and can be added again to a server
    that restarted.
    """

    def __init__(
        self, api_base: str, rtsp_base: str, client: httpx.AsyncClient, login: tuple[str, str] | None = None
    ) -> None:
        """Points the client at a MediaMTX.

        Args:
            api_base: Where its control API listens.
            rtsp_base: Where its RTSP listener is.
            client: The HTTP client the API calls go through.
            login: The user and password its control API asks for. The bundled
                server only answers the one this hub started it with.
        """
        self._api = api_base.rstrip("/")
        self._rtsp = rtsp_base.rstrip("/")
        self._client = client
        self._login = login
        self._pulled: dict[str, dict[str, Any]] = {}

    def rtsp_url(self, path: str) -> str:
        """Internal RTSP URL the server reads frames from."""
        return f"{self._rtsp}/{path}"

    async def list_paths(self) -> list[str]:
        """Names of currently active stream paths."""
        resp = await self._client.get(f"{self._api}/v3/paths/list", auth=self._login, timeout=5.0)
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
        await self._add_path(name, payload)
        self._pulled[name] = payload

    async def _add_path(self, name: str, payload: dict[str, Any]) -> None:
        resp = await self._client.post(
            f"{self._api}/v3/config/paths/add/{name}", json=payload, auth=self._login, timeout=5.0
        )
        if resp.status_code == 400:
            resp = await self._client.patch(
                f"{self._api}/v3/config/paths/patch/{name}", json=payload, auth=self._login, timeout=5.0
            )
        resp.raise_for_status()

    async def remove_path(self, name: str) -> None:
        """Deletes a managed path, ignoring paths that no longer exist."""
        self._pulled.pop(name, None)
        await self._client.delete(f"{self._api}/v3/config/paths/delete/{name}", auth=self._login, timeout=5.0)

    async def restore_paths(self) -> None:
        """Adds every pull path again, for a server that restarted and forgot them.

        A camera that is being watched finds its way back by reconnecting, but
        one asleep until its printer starts is only asked for by a viewer, and
        the server would answer that it has no such path.
        """
        for name, payload in list(self._pulled.items()):
            await self._add_path(name, payload)


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

    The control API can read every camera's source URL and add a path that runs
    a command, and on the desktop app it listens on the computer's own loopback,
    where any web page in a browser can reach it. The shipped config grants the
    API to nobody, so the one login that can use it is handed to the server in
    its environment and never written to disk.
    """

    def __init__(
        self,
        binary: str,
        config: str,
        api_base: str,
        api_login: tuple[str, str],
        restarted: Callable[[], Awaitable[None]],
    ) -> None:
        """Prepares the server without starting it.

        Args:
            binary: The MediaMTX executable.
            config: The config file it starts with.
            api_base: Where its control API will listen.
            api_login: The user and password to grant the control API to.
            restarted: Awaited each time a server started in place of one that
                exited is accepting connections.
        """
        self._binary = binary
        self._config = config
        self._api = urlsplit(api_base)
        user, password = api_login
        self._env = {
            **os.environ,
            f"{API_USER_ENV}_USER": user,
            f"{API_USER_ENV}_PASS": password,
            f"{API_USER_ENV}_PERMISSIONS_0_ACTION": "api",
        }
        self._restarted = restarted
        self._process: asyncio.subprocess.Process | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = False
        self._watcher: subprocess.Popen[bytes] | None = None
        self._watch_fd = -1
        self._job: Any = None

    async def start(self) -> None:
        """Launches the server and waits until its control API accepts connections."""
        self._supervisor = asyncio.ensure_future(self._run())
        await self._ready()

    async def _ready(self) -> bool:
        """Waits for the control API to accept connections, reporting whether it did in time."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + READY_TIMEOUT_S
        while loop.time() < deadline:
            if await self._listening():
                return True
            await asyncio.sleep(0.2)
        logger.error("MediaMTX did not accept connections within %ss", READY_TIMEOUT_S)
        return False

    async def _restore(self) -> None:
        try:
            if await self._ready():
                await self._restarted()
        except Exception as exc:
            logger.error("MediaMTX restarted and its camera paths could not be added again: %s", exc)

    async def _run(self) -> None:
        replacement = False
        while not self._stopping:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    self._binary,
                    self._config,
                    env=self._env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                logger.error("MediaMTX failed to launch (%s); retrying", exc)
                await asyncio.sleep(RESTART_DELAY_S)
                continue
            self._bind_lifetime(self._process.pid)
            restoring = asyncio.ensure_future(self._restore()) if replacement else None
            try:
                code = await self._process.wait()
            finally:
                if restoring is not None:
                    restoring.cancel()
            self._release_lifetime()
            if self._stopping:
                return
            logger.error("MediaMTX exited (code %s); restarting", code)
            await asyncio.sleep(RESTART_DELAY_S)
            replacement = True

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
