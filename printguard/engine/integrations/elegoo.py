"""Elegoo integration over the local Centauri and Moonraker protocols.

Elegoo's official Link SDK supports Centauri Carbon 1 and 2, Neptune 4
Pro/Plus/Max, OrangeStorm Giga and other Moonraker printers through one
local-LAN surface. Centauri models use raw WebSocket or MQTT connections
through pycentauri; Moonraker models reuse PrintGuard's Klipper adapter
instead of duplicating its HTTP implementation.

Official SDK and model list: https://github.com/ELEGOO-3D/elegoo-link
Centauri Python client: https://github.com/bjan/pycentauri
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pycentauri
from pycentauri.cc2 import CONTROL_TIMEOUT_S

from .base import DeviceAction, DeviceState, DeviceStatus, Heater, HttpFn, IntegrationAdapter
from .klipper import KlipperAdapter

_CENTAURI = "centauri"
_MOONRAKER = "moonraker"
_PRINTING = {1, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29}
_PAUSED = {5, 6}
_IDLE = {0, 7, 8, 9}
_ERROR = {14}
_CC2_JOB_STATES = {1, 2}
"""The Centauri Carbon 2 machine states that say whether a job is running: idle and printing.

Elegoo's SDK names the rest initialising, filament loading and unloading,
levelling, PID calibration, resonance testing, self-checking and updating:
https://github.com/ELEGOO-3D/elegoo-link/blob/main/src/lan/adapters/elegoo_fdm_cc2/elegoo_fdm_cc2_message_adapter.cpp
"""
_ACTIONS = {
    DeviceAction.PAUSE: "pause",
    DeviceAction.RESUME: "resume",
    DeviceAction.CANCEL: "stop",
}
_FRESH_STATUS_TIMEOUT_S = 10.0


class ElegooAdapter(IntegrationAdapter):
    """Controls supported Elegoo FDM printers directly on the local network."""

    id = "elegoo"
    label = "Elegoo"
    docs_url = "https://github.com/ELEGOO-3D/elegoo-link"
    setup_hint = (
        "Centauri Carbon 2 needs LAN Only Mode and its screen access code. "
        "Neptune 4 and OrangeStorm printers use their stock Moonraker service."
    )
    experimental = False
    formats = ("gcode",)
    heater_control = True
    slow_action_s = CONTROL_TIMEOUT_S
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
        self._polled: dict[tuple[str, str], Any] = {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Reads and normalises the active print state.

        A Centauri Carbon 2 that is starting up, moving filament, levelling or
        calibrating outside a job says nothing about one, so those read as
        unknown and the last answer stands.

        Raises:
            RuntimeError: If a Centauri printer has reported nothing since the
                last read, so an old state is never taken for the current one.
        """
        if self._family(config) == _MOONRAKER:
            return await self._moonraker.fetch_state(http, self._moonraker_config(config))
        async with self._centauri(config) as printer:
            status = await self._fresh_status(self.connection_key(config), printer)
        cc2 = status.raw.get("_cc2") or {}
        remaining = cc2.get("remaining_time_sec")
        return DeviceState(
            self._status(status.print_status, cc2.get("machine_status")),
            float(status.progress or 0.0),
            status.filename or None,
            remaining_s=int(remaining) if remaining is not None else None,
            nozzle=Heater.reported(status.temp_nozzle, status.temp_nozzle_target),
            bed=Heater.reported(status.temp_bed, status.temp_bed_target),
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Pauses, resumes or stops the active print."""
        if self._family(config) == _MOONRAKER:
            await self._moonraker.send(http, self._moonraker_config(config), action)
            return
        async with self._centauri(config) as printer:
            answer = await getattr(printer, _ACTIONS[action])()
        _require_ack(answer, _ACTIONS[action])

    async def heat(self, http: HttpFn, config: dict[str, Any], heater: str, target: float) -> None:
        """Sets a heater target, through Moonraker or pycentauri's set_temperatures."""
        if self._family(config) == _MOONRAKER:
            await self._moonraker.heat(http, self._moonraker_config(config), heater, target)
            return
        async with self._centauri(config) as printer:
            answer = await printer.set_temperatures(**{heater: target})
        _require_ack(answer, f"the {heater} target")

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Uploads to the printer's internal storage and starts the print.

        pycentauri transfers from a path, chunked and checksummed the way the
        printer expects, so the bytes pass through a temporary file.
        """
        if self._family(config) == _MOONRAKER:
            await self._moonraker.print_file(http, self._moonraker_config(config), filename, data)
            return
        async with self._centauri(config) as printer:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / filename
                await asyncio.to_thread(path.write_bytes, data)
                remote = await printer.upload_file(path, remote_name=filename)
            answer = await printer.start_print(remote)
        _require_ack(answer, f"to print {filename}")

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
        if config is not None and config.get("family") != _CENTAURI:
            return
        keys = (
            [self.connection_key(config)]
            if config is not None
            else list(self._connections.keys() | self._connection_locks.keys())
        )
        for key in keys:
            async with self._connection_locks.setdefault(key, asyncio.Lock()):
                printer = self._connections.pop(key, None)
                self._polled.pop(key, None)
                if printer is None:
                    continue
                mainboard_id = printer.mainboard_id
                if mainboard_id:
                    self._mainboard_ids[key[0]] = mainboard_id
                await printer.close()
        if config is None:
            self._connection_locks.clear()

    @asynccontextmanager
    async def _centauri(self, config: dict[str, Any]) -> AsyncIterator[Any]:
        """Yields the printer's connection and closes it when a call on it fails.

        A target pycentauri refuses before sending anything is a ValueError,
        which leaves the connection as it was.
        """
        try:
            yield await self._connect_centauri(config)
        except ValueError:
            raise
        except Exception:
            await self.close(config)
            raise

    async def _connect_centauri(self, config: dict[str, Any]) -> Any:
        key = self.connection_key(config)
        printer = self._connections.get(key)
        if printer is not None and not printer._closed:
            return printer
        async with self._connection_locks.setdefault(key, asyncio.Lock()):
            printer = self._connections.get(key)
            if printer is not None and not printer._closed:
                return printer
            mainboard_id = self._mainboard_ids.get(key[0]) or await self._discover_mainboard_id(key[0])
            printer = await pycentauri.connect_auto(
                key[0],
                access_code=key[1] or None,
                enable_control=True,
                mainboard_id=mainboard_id,
            )
            self._connections[key] = printer
            return printer

    async def _fresh_status(self, key: tuple[str, str], printer: Any) -> Any:
        """Reads a status the printer reported since the last read.

        pycentauri answers a Centauri Carbon 1 with the last status it pushed
        for as long as the socket stays open. A status already read is waited
        out through ``watch()``, which also asks a printer whose pushes have
        stalled for a new one.
        """
        status = await printer.status()
        if status is self._polled.get(key):
            try:
                status = await asyncio.wait_for(self._next_status(printer, status), _FRESH_STATUS_TIMEOUT_S)
            except asyncio.TimeoutError:
                raise RuntimeError("Elegoo printer stopped reporting its status") from None
        self._polled[key] = status
        return status

    async def _next_status(self, printer: Any, read: Any) -> Any:
        async with aclosing(printer.watch()) as pushed:
            async for status in pushed:
                if status is not read:
                    return status
        raise RuntimeError("Elegoo printer closed the connection")

    async def _discover_mainboard_id(self, host: str) -> str | None:
        resolved = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET)
        addresses = {entry[4][0] for entry in resolved}
        addresses.add(host)
        printers = await pycentauri.discover(timeout=1.0, retries=2)
        return next((printer.mainboard_id for printer in printers if printer.host in addresses and printer.mainboard_id), None)

    def connection_key(self, config: dict[str, Any]) -> tuple[str, str]:
        """A Centauri connection is one host under one access code."""
        return str(config.get("host")), str(config.get("access_code") or "")

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

    def _status(self, status: int | None, machine_state: int | None) -> DeviceStatus:
        if machine_state is not None and machine_state not in _CC2_JOB_STATES:
            return DeviceStatus.UNKNOWN
        if status in _PRINTING:
            return DeviceStatus.PRINTING
        if status in _PAUSED:
            return DeviceStatus.PAUSED
        if status in _IDLE:
            return DeviceStatus.IDLE
        if status in _ERROR:
            return DeviceStatus.ERROR
        return DeviceStatus.UNKNOWN


def _require_ack(response: Any, command: str) -> None:
    """Raises unless the printer acknowledged a command.

    A Centauri Carbon 1 answers every command, and a refused one differs only
    in a non-zero ``Ack``, which pycentauri hands back without raising.

    Args:
        response: The message pycentauri returned for the command.
        command: What was asked, for the error.

    Raises:
        RuntimeError: If the printer answered with a non-zero Ack.
    """
    ack = (response.inner.get("Data") or {}).get("Ack")
    if ack:
        raise RuntimeError(f"Elegoo printer refused {command}: Ack {ack}")
