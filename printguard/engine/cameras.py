"""Camera configuration, covering defaults, validation and serialisation."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import string
from typing import Any
from urllib.parse import urlsplit

from .bounds import clamp
from .urls import DEFAULT_PORTS

_WEBRTC_SCHEMES = ("webrtc", "whep", "wheps", "whip", "whips")
_WHEP_SCHEMES = ("whep", "wheps")
_WEBRTC_PATH_SEGMENTS = frozenset({"webrtc", "whep", "whip"})
_DEFAULT_PORTS = {**DEFAULT_PORTS, "rtmp": 1935, "rtmps": 443}
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_IPV4_SHORTHAND = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){0,3}")


def webrtc_endpoint(url: str) -> bool:
    """Whether a stream URL is a WebRTC signalling endpoint.

    PyAV/FFmpeg cannot ingest WebRTC, so the hub routes WHEP endpoints through
    MediaMTX while proprietary signalling remains unsupported. A feed is WebRTC
    when it uses an explicit signalling scheme or carries a signalling path
    segment such as camera-streamer's ``/webcam/webrtc``. Relative URLs, as
    Moonraker may report, are recognised too.
    """
    parsed = urlsplit(url)
    if parsed.scheme in _WEBRTC_SCHEMES:
        return True
    return any(segment.lower() in _WEBRTC_PATH_SEGMENTS for segment in parsed.path.split("/"))


def whep_endpoint(url: str) -> bool:
    """Whether a URL explicitly identifies a WHEP WebRTC egress endpoint."""
    parsed = urlsplit(url)
    if parsed.scheme in _WHEP_SCHEMES:
        return True
    return parsed.scheme in ("", "http", "https") and parsed.path.rstrip("/").rsplit("/", 1)[-1].lower() == "whep"


def tidy_stream_url(url: str) -> str:
    """Writes a stream address the way it opens, since a space around it or a capital in its scheme opens nothing.

    Args:
        url: The address as it was typed or pasted.

    Returns:
        It without the whitespace around it and with its scheme in lower case.
    """
    scheme, separator, rest = url.strip().partition("://")
    return f"{scheme.lower()}{separator}{rest}" if separator else scheme


def _plain_percent_escapes(text: str) -> str:
    """Writes each escape the way one spelling of it is: a letter or digit decoded, the rest in capitals."""

    def decode(escape: re.Match[str]) -> str:
        character = chr(int(escape.group()[1:], 16))
        return character if character in _UNRESERVED else escape.group().upper()

    return re.sub(r"%[0-9a-fA-F]{2}", decode, text)


def _plain_host(host: str) -> str:
    """A host with the spellings that name one machine written one way.

    Args:
        host: A host as ``urlsplit`` hands it back: lower case, without brackets.

    Returns:
        It without a trailing dot, a number-form IPv4 address such as ``127.1``
        written out in full, and an IPv6 address in its compressed form.
    """
    host = host.rstrip(".")
    try:
        if _IPV4_SHORTHAND.fullmatch(host):
            return socket.inet_ntoa(socket.inet_aton(host))
        return ipaddress.IPv6Address(host).compressed
    except (OSError, ValueError):
        return host


def same_stream(url: str) -> str:
    """The part of a stream address that says which stream it is, for telling two addresses apart.

    Args:
        url: A stream address.

    Returns:
        It tidied and written one way however it was typed: without a
        fragment, credentials, a port that is the scheme's own or a
        trailing slash, dot or bare ``?``, with its host in lower case and its
        query parameters in order, and with the escapes that spell a letter or
        digit decoded. A path keeps its case, since a server tells them apart.
    """
    tidy = tidy_stream_url(url).partition("#")[0]
    parts = urlsplit(tidy)
    if not parts.netloc:
        return tidy
    try:
        port = parts.port
    except ValueError:
        return tidy
    host = _plain_host(parts.hostname or "")
    if ":" in host:
        host = f"[{host}]"
    shown_port = f":{port}" if port is not None and port != _DEFAULT_PORTS.get(parts.scheme) else ""
    query = "&".join(sorted(pair for pair in parts.query.split("&") if pair))
    return _plain_percent_escapes(f"{parts.scheme}://{host}{shown_port}{parts.path.rstrip('/')}{'?' + query if query else ''}")


def declared_camera_id(device_id: str) -> str:
    """The id a device declared by the deployment registers under.

    Derived from the device's own path, so the camera comes back to the same
    registration after a restart, keeping the name and tuning it was given.

    Args:
        device_id: Path the platform opens the device at.

    Returns:
        A stable, path-safe camera id.
    """
    return f"dev-{hashlib.sha256(device_id.encode()).hexdigest()[:8]}"


CAMERA_DEFAULTS: dict[str, Any] = {
    "brightness": 1.0,
    "contrast": 1.0,
    "sharpness": 0.0,
    "crop": None,
    "rotation": 0,
    "detect_fps": 60.0,
}

_CLAMP = {"brightness": (0.25, 2.0), "contrast": (0.25, 2.0), "sharpness": (0.0, 2.0), "detect_fps": (0.1, 60.0)}
_ROTATIONS = (0, 90, 180, 270)


def _sanitise_crop(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("a crop holds x, y, w and h, each a share of the frame")
    x = clamp("crop x", raw.get("x", 0), 0.0, 1.0)
    y = clamp("crop y", raw.get("y", 0), 0.0, 1.0)
    w = clamp("crop w", raw.get("w", 1), 0.01, 1.0 - x)
    h = clamp("crop h", raw.get("h", 1), 0.01, 1.0 - y)
    if x == 0 and y == 0 and w == 1 and h == 1:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _sanitise_rotation(raw: Any) -> int:
    if raw not in _ROTATIONS:
        raise ValueError("rotation is 0, 90, 180 or 270")
    return int(raw)


def sanitise_camera(camera_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a camera patch over defaults or an existing record.

    Args:
        camera_id: Stable identifier for the camera.
        patch: Partial camera fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated camera settings record.

    Raises:
        ValueError: If the patch names a setting a camera does not have, a
            tuning value or a side of the crop is not a finite number, or the
            name, crop or rotation is not of the kind it takes.
    """
    unknown = sorted(set(patch) - set(CAMERA_DEFAULTS) - {"name"})
    if unknown:
        raise ValueError(f"a camera has no {unknown[0]} setting")
    record = {**(base or CAMERA_DEFAULTS), **patch, "id": camera_id}
    if "name" in patch:
        if not isinstance(patch["name"], str):
            raise ValueError("a camera's name is text")
        record["name"] = patch["name"].strip() or "Camera"
    for key in ("brightness", "contrast", "sharpness", "detect_fps"):
        record[key] = clamp(key, record[key], *_CLAMP[key])
    record["crop"] = _sanitise_crop(record.get("crop"))
    record["rotation"] = _sanitise_rotation(record.get("rotation"))
    return record
