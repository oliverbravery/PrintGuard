"""Camera configuration: defaults, validation and serialisation."""

from __future__ import annotations

from typing import Any

CAMERA_DEFAULTS: dict[str, Any] = {
    "brightness": 1.0,
    "contrast": 1.0,
    "sharpness": 0.0,
    "crop": None,
}

_CLAMP = {"brightness": (0.25, 2.0), "contrast": (0.25, 2.0), "sharpness": (0.0, 2.0)}


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
    return record
