"""Camera configuration: defaults, validation and serialisation."""

from __future__ import annotations

from typing import Any

CAMERA_DEFAULTS: dict[str, Any] = {
    "brightness": 1.0,
    "contrast": 1.0,
    "sharpness": 0.0,
}

_CLAMPS = {"brightness": (0.25, 2.0), "contrast": (0.25, 2.0), "sharpness": (0.0, 2.0)}


def _clamp(key: str, value: float) -> float:
    low, high = _CLAMPS[key]
    return max(low, min(high, value))


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
    return record
