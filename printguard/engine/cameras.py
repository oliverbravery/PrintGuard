"""Camera configuration, covering defaults, validation and serialisation."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from .bounds import clamp

_WEBRTC_SCHEMES = ("webrtc", "whep", "wheps", "whip", "whips")
_WHEP_SCHEMES = ("whep", "wheps")
_WEBRTC_PATH_SEGMENTS = frozenset({"webrtc", "whep", "whip"})


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


def same_stream(url: str) -> str:
    """The part of a stream address that says which stream it is, for telling two addresses apart.

    Args:
        url: A stream address.

    Returns:
        It tidied, with its host in lower case and without a fragment, which
        the camera is never sent.
    """
    scheme, separator, rest = tidy_stream_url(url).partition("#")[0].partition("://")
    host, slash, path = rest.partition("/")
    return f"{scheme}{separator}{host.lower()}{slash}{path}"


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
