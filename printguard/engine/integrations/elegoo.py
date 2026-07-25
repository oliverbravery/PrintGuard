"""Elegoo integration over the local Centauri and Moonraker protocols.

Elegoo's official Link SDK supports Centauri Carbon 1 and 2, Neptune 4
Pro/Plus/Max, OrangeStorm Giga and other Moonraker printers through one
local-LAN surface. Centauri models use raw WebSocket or MQTT connections,
so this adapter is hub-only; Moonraker models reuse PrintGuard's Klipper
adapter instead of duplicating its HTTP implementation.

Official SDK and model list: https://github.com/ELEGOO-3D/elegoo-link
Centauri Python client: https://github.com/bjan/pycentauri
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import DeviceAction, DeviceState, DeviceStatus, HttpFn, IntegrationAdapter
from .klipper import KlipperAdapter

_CENTAURI = "centauri"
_MOONRAKER = "moonraker"
_PRINTING = {1, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29}
_PAUSED = {5, 6}
_IDLE = {0, 7, 8, 9}
_ERROR = {14}
_ACTIONS = {
    DeviceAction.PAUSE: "pause",
    DeviceAction.RESUME: "resume",
    DeviceAction.CANCEL: "stop",
}


class ElegooAdapter(IntegrationAdapter):
    """Controls supported Elegoo FDM printers directly on the local network."""

    id = "elegoo"
    label = "Elegoo"
    docs_url = "https://github.com/ELEGOO-3D/elegoo-link"
    setup_hint = (
        "Centauri Carbon 2 needs LAN Only Mode and its screen access code. "
        "Neptune 4 and OrangeStorm printers use their stock Moonraker service."
    )
    browser_ok = False
    experimental = False
    schema = {
        "type": "object",
        "properties": {
            "family": {
                "type": "string",
                "title": "Printer family",
                "enum": [_CENTAURI, _MOONRAKER],
                "enum_labels": ["Centauri Carbon 1 / 2", "Neptune 4 / OrangeStorm Giga"],
            },
            "host": {"type": "string", "title": "Printer IP or hostname", "placeholder": "192.168.1.80"},
            "access_code": {
                "type": "string",
                "title": "Access code (Centauri Carbon 2 only)",
                "secret": True,
                "placeholder": "Shown under the printer's network settings",
            },
            "api_key": {
                "type": "string",
                "title": "Moonraker API key (optional)",
                "secret": True,
                "placeholder": "Leave blank if unset",
            },
        },
        "required": ["family", "host"],
    }

    def __init__(self) -> None:
        self._moonraker = KlipperAdapter()
        self._connections: dict[tuple[str, str], Any] = {}
        self._connection_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._mainboard_ids: dict[str, str] = {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Reads and normalises the active print state."""
        if self._family(config) == _MOONRAKER:
            return await self._moonraker.fetch_state(http, self._moonraker_config(config))
        try:
            printer = await self._connect_centauri(config)
            status = await printer.status()
        except Exception:
            await self.close(config)
            raise
        return DeviceState(
            self._status(status.print_status),
            float(status.progress or 0.0),
            status.filename or None,
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Pauses, resumes or stops the active print."""
        if self._family(config) == _MOONRAKER:
            await self._moonraker.send(http, self._moonraker_config(config), action)
            return
        try:
            printer = await self._connect_centauri(config)
            await getattr(printer, _ACTIONS[action])()
        except Exception:
            await self.close(config)
            raise

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Exposes the built-in Centauri camera or Moonraker webcams."""
        if self._family(config) == _MOONRAKER:
            return await self._moonraker.cameras(http, self._moonraker_config(config))
        printer = await self._connect_centauri(config)
        return [
            {
                "key": "chamber",
                "name": "Chamber camera",
                "source": {"kind": "url", "url": f"http://{config['host']}:{printer.camera_port}/video"},
            }
        ]

    async def close(self, config: dict[str, Any] | None = None) -> None:
        """Closes persistent Centauri connections."""
        if config is not None and self._family(config) != _CENTAURI:
            return
        keys = (
            [self._connection_key(config)]
            if config is not None
            else list(self._connections.keys() | self._connection_locks.keys())
        )
        for key in keys:
            async with self._connection_locks.setdefault(key, asyncio.Lock()):
                printer = self._connections.pop(key, None)
                if printer is None:
                    continue
                mainboard_id = printer.mainboard_id
                if mainboard_id:
                    self._mainboard_ids[key[0]] = mainboard_id
                await printer.close()
        if config is None:
            self._connection_locks.clear()

    async def _connect_centauri(self, config: dict[str, Any]) -> Any:
        from pycentauri import connect_auto

        key = self._connection_key(config)
        printer = self._connections.get(key)
        if printer is not None and not printer._closed:
            return printer
        async with self._connection_locks.setdefault(key, asyncio.Lock()):
            printer = self._connections.get(key)
            if printer is not None and not printer._closed:
                return printer
            mainboard_id = self._mainboard_ids.get(key[0]) or await self._discover_mainboard_id(key[0])
            printer = await connect_auto(
                key[0],
                access_code=key[1] or None,
                enable_control=True,
                mainboard_id=mainboard_id,
            )
            self._connections[key] = printer
            return printer

    async def _discover_mainboard_id(self, host: str) -> str | None:
        import socket

        from pycentauri import discover

        resolved = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET)
        addresses = {entry[4][0] for entry in resolved}
        addresses.add(host)
        printers = await discover(timeout=1.0, retries=2)
        return next((printer.mainboard_id for printer in printers if printer.host in addresses and printer.mainboard_id), None)

    def _connection_key(self, config: dict[str, Any]) -> tuple[str, str]:
        return str(config["host"]), str(config.get("access_code") or "")

    def _family(self, config: dict[str, Any]) -> str:
        family = str(config["family"])
        if family not in (_CENTAURI, _MOONRAKER):
            raise ValueError(f"unknown Elegoo printer family {family!r}")
        return family

    def _moonraker_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "base_url": f"http://{config['host']}:7125",
            "api_key": str(config.get("api_key") or ""),
        }

    def _status(self, status: int | None) -> DeviceStatus:
        if status in _PRINTING:
            return DeviceStatus.PRINTING
        if status in _PAUSED:
            return DeviceStatus.PAUSED
        if status in _IDLE:
            return DeviceStatus.IDLE
        if status in _ERROR:
            return DeviceStatus.ERROR
        return DeviceStatus.UNKNOWN
