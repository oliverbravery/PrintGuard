"""Klipper integration via the Moonraker API.

API reference: https://moonraker.readthedocs.io/en/latest/external_api/introduction/
Authorization (trusted_clients, API keys): https://moonraker.readthedocs.io/en/latest/configuration/#authorization
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..adapters import multipart_form
from ..cameras import webrtc_endpoint, whep_endpoint
from .base import DeviceAction, DeviceState, DeviceStatus, Heater, HttpFn, IntegrationAdapter, require_reply, webcam_url

_UPLOAD_TIMEOUT_S = 180.0
_API_PORTS = range(7125, 7200)
"""Moonraker's own ports: 7125, one more for each further instance on the host, and 7130 for TLS."""
_OK = {"result": "ok"}
_HEATERS = {"nozzle": "extruder", "bed": "heater_bed"}
_STATUS_MAP = {
    "printing": DeviceStatus.PRINTING,
    "paused": DeviceStatus.PAUSED,
    "standby": DeviceStatus.IDLE,
    "complete": DeviceStatus.IDLE,
    "cancelled": DeviceStatus.IDLE,
    "error": DeviceStatus.ERROR,
}


class KlipperAdapter(IntegrationAdapter):
    """Talks to Moonraker's HTTP API, optionally with an API key."""

    id = "klipper"
    label = "Klipper (Moonraker)"
    docs_url = "https://moonraker.readthedocs.io/en/latest/external_api/introduction/"
    setup_url = "https://moonraker.readthedocs.io/en/latest/configuration/#authorization"
    formats = ("gcode", "gco", "g")
    heater_control = True
    setup_hint = (
        "On a trusted LAN Moonraker needs no key. Otherwise add the hub's address to "
        "trusted_clients in the [authorization] section of moonraker.conf, or enter an API key."
    )
    schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "format": "uri",
                "title": "Base URL",
                "placeholder": "http://192.168.1.60:7125",
            },
            "api_key": {"type": "string", "title": "API key (optional)", "secret": True, "placeholder": "Leave blank if unset"},
        },
        "required": ["base_url"],
    }

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = str(config.get("api_key") or "")
        return {"X-Api-Key": key} if key else {}

    async def fetch_state(self, http: HttpFn, config: dict[str, Any]) -> DeviceState:
        """Queries print_stats, virtual_sdcard and the two heaters in one call.

        Klipper keeps no estimate of its own, so the time left is projected
        from how long the print has run against how far through the file it is.

        Raises:
            PermissionError: If Moonraker rejects the API key, or wants one.
            RuntimeError: If it answers with anything but the objects.
        """
        url = f"{config['base_url'].rstrip('/')}/printer/objects/query?print_stats&virtual_sdcard&extruder&heater_bed"
        status, body = await http("GET", url, headers=self._headers(config))
        if status in (401, 403):
            raise PermissionError(f"Moonraker rejected the API key: HTTP {status}")
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"Moonraker did not answer like its API: HTTP {status}")
        objects = (body.get("result") or {}).get("status") or {}
        stats = objects.get("print_stats") or {}
        matched = _STATUS_MAP.get(str(stats.get("state", "")).lower(), DeviceStatus.UNKNOWN)
        fraction = float((objects.get("virtual_sdcard") or {}).get("progress") or 0.0)
        duration = float(stats.get("print_duration") or 0.0)
        extruder, bed = objects.get("extruder") or {}, objects.get("heater_bed") or {}
        return DeviceState(
            matched,
            fraction * 100.0,
            stats.get("filename") or None,
            remaining_s=int(duration * (1.0 - fraction) / fraction) if fraction > 0.0 and duration > 0.0 else None,
            nozzle=Heater.reported(extruder.get("temperature"), extruder.get("target")),
            bed=Heater.reported(bed.get("temperature"), bed.get("target")),
        )

    async def send(self, http: HttpFn, config: dict[str, Any], action: DeviceAction) -> None:
        """Issues pause/resume/cancel through /printer/print endpoints, which answer ``{"result": "ok"}``.

        Raises:
            RuntimeError: If Moonraker rejects the command or answers with anything else.
        """
        status, body = await http(
            "POST",
            f"{config['base_url'].rstrip('/')}/printer/print/{action.value}",
            headers=self._headers(config),
        )
        require_reply("Moonraker", action.value, status, body == _OK)

    async def heat(self, http: HttpFn, config: dict[str, Any], heater: str, target: float) -> None:
        """Sets a heater target with SET_HEATER_TEMPERATURE through /printer/gcode/script.

        Raises:
            RuntimeError: If Moonraker rejects the target or answers with anything but ``{"result": "ok"}``.
        """
        status, body = await http(
            "POST",
            f"{config['base_url'].rstrip('/')}/printer/gcode/script",
            headers=self._headers(config),
            json={"script": f"SET_HEATER_TEMPERATURE HEATER={_HEATERS[heater]} TARGET={target:g}"},
        )
        require_reply("Moonraker", f"the {heater} target", status, body == _OK)

    async def print_file(self, http: HttpFn, config: dict[str, Any], filename: str, data: bytes) -> None:
        """Uploads into the gcodes root through /server/files/upload and starts it.

        Moonraker answers 201 for a file it stored whether or not Klipper then
        started it, and says which in ``print_started``. This reply is the one
        Moonraker does not wrap in ``result``. A file that cannot start at once
        is held in the job queue when ``queue_gcode_uploads`` is set, and
        ``print_queued`` says so.

        Raises:
            RuntimeError: If Moonraker refuses the file, does not answer with
                its 201 upload reply, or does not start the print.
        """
        headers, body = multipart_form({"root": "gcodes", "print": "true"}, "file", filename, data, "application/octet-stream")
        status, reply = await http(
            "POST",
            f"{config['base_url'].rstrip('/')}/server/files/upload",
            headers={**self._headers(config), **headers},
            data=body,
            timeout=_UPLOAD_TIMEOUT_S,
        )
        require_reply("Moonraker", filename, status, status == 201 and isinstance(reply, dict) and "print_started" in reply)
        if reply["print_started"]:
            return
        if reply.get("print_queued"):
            raise RuntimeError(f"Moonraker queued {filename} and will print it when the printer is free")
        raise RuntimeError(f"Moonraker stored {filename} but did not start printing it")

    async def cameras(self, http: HttpFn, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Lists Moonraker's registered webcams via /server/webcams/list.

        Each webcam's stream_url may be relative, resolved against the host's web
        port (see ``webcam_url``); its stable uid keys the registered camera, or
        its name on a Moonraker too old to give one. A webcam on MediaMTX or
        go2rtc is pulled from that server's WHEP endpoint, which the hub's
        MediaMTX client reads. camera-streamer, the Crowsnest V5 default,
        signals WebRTC its own way, so it is redirected to its MJPEG endpoint.
        A webcam on any other WebRTC service with no MJPEG endpoint to derive,
        or one that is a web page or an H.264 stream on a WebSocket, is left out.
        """
        status, body = await http("GET", f"{config['base_url'].rstrip('/')}/server/webcams/list", headers=self._headers(config))
        if status != 200 or not isinstance(body, dict):
            return []
        found: list[dict[str, Any]] = []
        for webcam in (body.get("result") or {}).get("webcams") or []:
            stream = str(webcam.get("stream_url") or "")
            service = str(webcam.get("service") or "").lower()
            if not webcam.get("enabled", True) or service in _UNREADABLE_SERVICES:
                continue
            if stream and service in _WHEP_ENDPOINTS and not whep_endpoint(stream):
                stream = _WHEP_ENDPOINTS[service](webcam_url(config["base_url"], stream, _API_PORTS))
            elif ("webrtc" in service or webrtc_endpoint(stream)) and not whep_endpoint(stream):
                stream = _mjpeg_endpoint(webcam)
            if not stream or (webrtc_endpoint(stream) and not whep_endpoint(stream)):
                continue
            found.append(
                {
                    "key": _UNSAFE_IN_A_KEY.sub("-", str(webcam.get("uid") or webcam.get("name") or len(found))),
                    "name": webcam.get("name") or "Webcam",
                    "source": {"kind": "url", "url": webcam_url(config["base_url"], stream, _API_PORTS)},
                }
            )
        return found


def _mjpeg_endpoint(webcam: dict[str, Any]) -> str:
    """Derives camera-streamer's MJPEG endpoint for a WebRTC-advertised webcam.

    camera-streamer serves the same feed as MJPEG alongside WebRTC, at the
    sibling of its snapshot (``…/?action=snapshot`` becomes ``…/?action=stream``)
    or of its WebRTC path (``…/webrtc`` becomes ``…/stream``). The snapshot is preferred as
    Moonraker reports it verbatim; an empty string means none could be derived.
    """
    snapshot = str(webcam.get("snapshot_url") or "")
    if snapshot:
        return _stream_sibling(snapshot, "snapshot")
    stream = str(webcam.get("stream_url") or "")
    mjpeg = _stream_sibling(stream, "webrtc")
    return "" if mjpeg == stream else mjpeg


def _stream_sibling(url: str, named: str) -> str:
    """Swaps a name for ``stream`` in the last part of a URL's path and in its query, never in its host."""
    parts = urlsplit(url)
    path = re.sub(rf"{named}(?=[^/]*/?$)", "stream", parts.path)
    return urlunsplit(parts._replace(path=path, query=parts.query.replace(named, "stream")))


def _mediamtx_whep(stream: str) -> str:
    """MediaMTX serves WHEP under the path's own page, where Mainsail looks for it too."""
    parts = urlsplit(stream)
    return urlunsplit(parts._replace(path=f"{parts.path.rstrip('/')}/whep"))


def _go2rtc_whep(stream: str) -> str:
    """go2rtc serves WHEP at ``api/webrtc`` beside whichever of its pages Moonraker was given.

    The path gives no sign of WHEP, so the address carries the scheme that says so.
    """
    parts = urlsplit(stream)
    path = re.sub(r"(api/(webrtc|ws)|[^/]*)$", "api/webrtc", parts.path, count=1)
    return urlunsplit(parts._replace(scheme="wheps" if parts.scheme == "https" else "whep", path=path))


_WHEP_ENDPOINTS = {"webrtc-mediamtx": _mediamtx_whep, "webrtc-go2rtc": _go2rtc_whep}
"""Moonraker's webcam services that serve WHEP, each with how its endpoint is found.

Mainsail's player builds the same MediaMTX address, and go2rtc's is the WHEP
route beside the socket Mainsail's player opens:
https://github.com/mainsail-crew/mainsail/tree/develop/src/components/webcams/streamers
"""
_UNREADABLE_SERVICES = {"iframe", "jmuxer-stream"}
"""Moonraker's webcam services that are a web page and raw H.264 on a WebSocket, neither of which the hub reads."""
_UNSAFE_IN_A_KEY = re.compile(r"[^\w.~-]", re.ASCII)
"""A camera's key ends up in its id, which is also its MediaMTX path."""
