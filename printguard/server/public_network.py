"""Connections that stay off the network the hub sits on.

A plugin without ``net:local`` may reach the internet and nothing around it. A
check made before the request would be the wrong place to enforce that, since the
name is resolved again to connect and a resolver an attacker runs can answer a
public address the first time and ``127.0.0.1`` the second. So the check is made
on the connection: the name is resolved once, every answer is checked, and the
socket is opened to one of the addresses that was. TLS and the ``Host`` header
still use the name, since only the address the socket goes to is replaced.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any, Awaitable, Callable, Iterable, TypeVar

import httpcore
import httpx

from ..engine import urls

Connected = TypeVar("Connected")


async def connect_to_public(host: str, port: int, connect: Callable[[str], Awaitable[Connected]]) -> Connected:
    """Opens a connection to one of the public addresses a host resolves to.

    Args:
        host: A name or an address.
        port: The port to connect to.
        connect: Opens a connection to the address it is handed.

    Returns:
        What ``connect`` returned for the first address that took it.

    Raises:
        PermissionError: If the host is, or any answer for it is, an address on
            this network.
        OSError: If none of the addresses could be reached.
    """
    answers = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if any(urls.is_local_address(address) for address in addresses):
        raise PermissionError("the address is on this network")
    failure: Exception = OSError(f"{host} has no address")
    for address in addresses:
        try:
            return await connect(address)
        except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
            failure = exc
    raise failure


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Opens every connection to an address that was checked, never to the name."""

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Resolves the host, checks it and connects to the address it settled on."""
        return await connect_to_public(
            host, port, lambda address: self._backend.connect_tcp(address, port, timeout, local_address, socket_options)
        )

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None) -> httpcore.AsyncNetworkStream:
        """Refuses a socket file, which is always on this machine."""
        raise PermissionError("the address is on this network")

    async def sleep(self, seconds: float) -> None:
        """Waits, as the backend it wraps does."""
        await self._backend.sleep(seconds)


class PublicOnlyTransport(httpx.AsyncHTTPTransport):
    """An HTTP transport that connects only through ``PublicOnlyBackend``.

    httpx offers no way to hand its connection pool a network backend, so the
    pool it builds is swapped for one that has it. A proxy named in the
    environment is not used, since the proxy would resolve the name.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pool = httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=PublicOnlyBackend())
