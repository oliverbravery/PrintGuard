"""The shape of the settings only the dashboard reads: theme, custom themes, glass and layout.

The engine keeps these and acts on none of them. It still checks their shape,
since a plugin holding the settings grant or an API token can save them, and
every dashboard renders what was saved.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .bounds import clamp

BASES = ("dark", "light")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
GLASS_KEYS = ("opacity", "tone")


def _theme(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not all(isinstance(raw.get(key), str) for key in ("id", "name")):
        raise ValueError("a custom theme needs an id and a name")
    if raw.get("base") not in BASES or not isinstance(raw.get("colors"), dict):
        raise ValueError(f"the theme {raw['name']!r} needs a dark or light base and its colours")
    if not all(isinstance(colour, str) and COLOUR.match(colour) for colour in raw["colors"].values()):
        raise ValueError(f"the theme {raw['name']!r} has a colour that is not written #rrggbb")
    return {"id": raw["id"], "name": raw["name"], "base": raw["base"], "colors": raw["colors"]}


def _layout(raw: Any) -> dict[str, Any]:
    sections = raw.values() if isinstance(raw, dict) else [None]
    for section in sections:
        lists = section.values() if isinstance(section, dict) else [None]
        if not all(isinstance(ids, list) and all(isinstance(item, str) for item in ids) for ids in lists):
            raise ValueError("a layout holds lists of ids, such as order, pinned and hidden, under monitors and cameras")
    return raw


def _name(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("theme names a colour scheme or a custom theme")
    return raw


def _themes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("themes is a list of custom themes")
    return [_theme(theme) for theme in raw]


def _glass(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError("glass holds an opacity and a tone")
    return {key: clamp(f"glass {key}", raw.get(key, 0.0), 0.0, 1.0) for key in GLASS_KEYS}


CHECKS: dict[str, Callable[[Any], Any]] = {"theme": _name, "themes": _themes, "glass": _glass, "layout": _layout}
"""What each of the dashboard's own settings is checked with, raising ValueError for one of the wrong shape."""


def sanitise(settings: dict[str, Any]) -> dict[str, Any]:
    """Checks the dashboard's own settings are ones every dashboard can render.

    Args:
        settings: The whole settings record, with any patch already applied.

    Returns:
        The theme, custom themes, glass and layout to store.

    Raises:
        ValueError: If one of them has the wrong shape, naming which.
    """
    return {key: check(settings[key]) for key, check in CHECKS.items()}
