"""Long-lived WebSockets held open for plugins.

A plugin runs and returns, so it cannot hold a connection itself. It names one
with a tag, PrintGuard keeps it, and every frame comes back as a ``socket``
event carrying that tag.

Connections belong to the plugin that opened them and are dropped when it is
disabled, reinstalled or removed.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)

MAX_PER_PLUGIN = 4
MAX_TEXT_BYTES = 64 * 1024


class Socket(Protocol):
    """One open connection, as a platform hands it back."""

    async def send(self, text: str) -> None:
        """Writes one text frame."""
        ...

    async def close(self) -> None:
        """Closes the connection and stops its reader."""
        ...


OpenFn = Callable[[str, Callable[[str, str], None]], Awaitable[Socket]]
"""Opens a URL and calls back with ``(state, text)`` for every frame.

State is ``open`` when the connection is up, ``message`` for each frame, and
``closed`` once it ends for any reason.
"""


class SocketBroker:
    """Holds every plugin's open connections, keyed by plugin and tag."""

    def __init__(self, open_socket: OpenFn, emit: Callable[[dict[str, Any]], None]) -> None:
        self._open = open_socket
        self._emit = emit
        self._sockets: dict[tuple[str, str], Socket] = {}

    async def act(self, plugin_id: str, action: str, tag: str, url: str, text: str) -> None:
        """Opens, sends on or closes one of a plugin's connections.

        Args:
            plugin_id: Whose connection it is.
            action: ``open``, ``send`` or ``close``.
            tag: The plugin's own name for the connection.
            url: Where to connect, for ``open``.
            text: The frame to write, for ``send``.

        Raises:
            ValueError: If the tag is missing, the plugin is holding as many
                connections as it may, or a frame is too large.
            KeyError: If sending on or closing a connection it has not opened.
        """
        if not tag:
            raise ValueError("a socket needs a tag to answer on")
        key = (plugin_id, tag)
        if action == "open":
            await self._open_one(key, url)
        elif action == "send":
            if len(text.encode()) > MAX_TEXT_BYTES:
                raise ValueError(f"a frame is {MAX_TEXT_BYTES // 1024} KB at most")
            await self._sockets[key].send(text)
        elif action == "close":
            await self.drop(plugin_id, tag)

    async def _open_one(self, key: tuple[str, str], url: str) -> None:
        if key in self._sockets:
            return
        if sum(1 for held in self._sockets if held[0] == key[0]) >= MAX_PER_PLUGIN:
            raise ValueError(f"a plugin holds {MAX_PER_PLUGIN} sockets at most")
        plugin_id, tag = key

        def arrived(state: str, text: str) -> None:
            if state == "closed":
                self._sockets.pop(key, None)
            self._emit({"event": "socket", "id": plugin_id, "tag": tag, "state": state, "text": text})

        self._sockets[key] = await self._open(url, arrived)
        logger.info("plugin %s opened socket %s", plugin_id, tag)

    async def drop(self, plugin_id: str, tag: str) -> None:
        """Closes one connection, if it is open."""
        socket = self._sockets.pop((plugin_id, tag), None)
        if socket is not None:
            await socket.close()

    async def drop_all(self, keep: set[str]) -> None:
        """Closes every connection except those of the plugins named."""
        for plugin_id, tag in [key for key in self._sockets if key[0] not in keep]:
            await self.drop(plugin_id, tag)
