"""Camera configuration: defaults, validation and serialisation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

_WEBRTC_SCHEMES = ("webrtc", "whep", "whip")
_WEBRTC_PATH_SEGMENTS = frozenset({"webrtc", "whep", "whip"})


def webrtc_endpoint(url: str) -> bool:
    """Whether a stream URL is a WebRTC (WHEP/WHIP) endpoint FFmpeg cannot ingest.

    PrintGuard reads cameras with PyAV/FFmpeg, which speaks RTSP/RTMP and HTTP
    MJPEG/HLS but not WebRTC. A feed is WebRTC when it uses an explicit signalling
    scheme (``webrtc://``/``whep://``/``whip://``) or, over HTTP, carries a
    signalling path segment such as ``/webrtc`` — camera-streamer serves its
    WebRTC stream at ``/webcam/webrtc``. Relative URLs, as Moonraker may report,
    are recognised too.
    """
    parsed = urlsplit(url)
    if parsed.scheme in _WEBRTC_SCHEMES:
        return True
    return any(segment.lower() in _WEBRTC_PATH_SEGMENTS for segment in parsed.path.split("/"))


CAMERA_DEFAULTS: dict[str, Any] = {
    "brightness": 1.0,
    "contrast": 1.0,
    "sharpness": 0.0,
    "crop": None,
    "rotation": 0,
}

_CLAMP = {"brightness": (0.25, 2.0), "contrast": (0.25, 2.0), "sharpness": (0.0, 2.0)}
_ROTATIONS = (0, 90, 180, 270)


def _clamp(key: str, value: float) -> float:
    low, high = _CLAMP[key]
    return max(low, min(high, value))


def _sanitise_crop(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        x = max(0.0, min(1.0, float(raw.get("x", 0))))
        y = max(0.0, min(1.0, float(raw.get("y", 0))))
        w = max(0.01, min(1.0 - x, float(raw.get("w", 1))))
        h = max(0.01, min(1.0 - y, float(raw.get("h", 1))))
    except (TypeError, ValueError):
        return None
    if x == 0 and y == 0 and w == 1 and h == 1:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _sanitise_rotation(raw: Any) -> int:
    try:
        rotation = int(raw) % 360
    except (TypeError, ValueError):
        return 0
    return rotation if rotation in _ROTATIONS else 0


def sanitise_camera(camera_id: str, patch: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merges a camera patch over defaults or an existing record.

    Args:
        camera_id: Stable identifier for the camera.
        patch: Partial camera fields supplied by the UI.
        base: Existing record when updating, else None.

    Returns:
        A complete, validated camera settings record.
    """
    record = {**(base or CAMERA_DEFAULTS), **patch, "id": camera_id}
    if "name" in patch or base:
        record["name"] = str(record.get("name", "Camera")).strip() or "Camera"
    record["brightness"] = _clamp("brightness", float(record["brightness"]))
    record["contrast"] = _clamp("contrast", float(record["contrast"]))
    record["sharpness"] = _clamp("sharpness", float(record["sharpness"]))
    record["crop"] = _sanitise_crop(record.get("crop"))
    record["rotation"] = _sanitise_rotation(record.get("rotation"))
    return record
