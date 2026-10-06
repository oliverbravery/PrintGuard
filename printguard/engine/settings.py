"""What each stored setting may hold.

The same checks run on a settings command and on the settings read back when
the hub starts, so a saved value that no command could have written is put
back to its default there instead of stopping the hub or every later edit.
"""

from __future__ import annotations

from typing import Any, Callable

from . import appearance
from .printers import sanitise_presets
from .watchdog import clamp_grace


def _one_of(label: str, *options: str) -> Callable[[Any], Any]:
    def check(raw: Any) -> Any:
        if raw not in options:
            raise ValueError(f"{label} must be {', '.join(options[:-1])} or {options[-1]}")
        return raw

    return check


def _true_or_false(raw: Any) -> bool:
    if not isinstance(raw, bool):
        raise ValueError("update_check is true or false")
    return raw


def _address(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("catalogue_url is an address")
    return raw


def _channels(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or not all(isinstance(config, dict) for config in raw.values()):
        raise ValueError("notifiers holds a config for each channel")
    return raw


def _broker(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("mqtt holds the broker's settings")
    return raw


CHECKS: dict[str, Callable[[Any], Any]] = {
    **appearance.CHECKS,
    "notifiers": _channels,
    "update_check": _true_or_false,
    "mqtt": _broker,
    "inference_runtime": _one_of("inference runtime", "auto", "litert", "onnx"),
    "catalogue_url": _address,
    "fault_grace_s": clamp_grace,
    "preheat": sanitise_presets,
    "feedback": _one_of("feedback", "ask", "off"),
}
"""What each setting is checked with, raising ValueError for one of the wrong kind and returning it as it is stored."""


def require_broker(mqtt: dict[str, Any]) -> None:
    """Checks broker settings a user has just saved, which a stored one may not meet.

    Args:
        mqtt: The broker settings as they would be stored.

    Raises:
        ValueError: If the port is set and is not a whole number from 1 to
            65535, the host is not text, or the bridge is enabled with no host.
    """
    port = mqtt.get("port")
    if port not in (None, "") and not (type(port) is int and 1 <= port <= 65535):
        raise ValueError("MQTT port must be a whole number from 1 to 65535")
    host = mqtt.get("host") or ""
    if not isinstance(host, str):
        raise ValueError("MQTT host is the broker's address")
    if mqtt.get("enabled") and not host.strip():
        raise ValueError("MQTT needs the broker's host before it is enabled")
