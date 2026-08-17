"""Rewrites the manifest JSON Schema from the engine's own tables.

An editor reads it through the ``$schema`` key in a plugin.json, so what it
offers and what it marks wrong is exactly what the engine accepts. Run it after
changing a permission, a surface or an event, and commit what it writes.

    uv run python plugins/schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printguard.engine import plugins  # noqa: E402

HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "plugin.schema.json"
SCHEMA_URL = "https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/plugin.schema.json"

SURFACE_HELP = {
    "panel": "A panel of its own on the dashboard.",
    "float": "A window that floats above other apps, holding whatever render last returned.",
    "monitor": "A button on every monitor tile, calling your action with the monitor's id.",
}


def choices(described: dict[str, str]) -> list[dict[str, str]]:
    """Turns names and their help into enum entries an editor can describe.

    Args:
        described: Each accepted value mapped to the line shown beside it.

    Returns:
        One constant subschema per value, which is how an editor offers a
        description with each completion.
    """
    return [{"const": name, "description": text} for name, text in described.items()]


def schema() -> dict:
    """Builds the schema a plugin.json is completed and validated against.

    Returns:
        The whole document, with the permission, surface and event tables read
        straight from the engine so the two cannot disagree.
    """
    permissions = {name: spec["description"] for name, spec in plugins.PERMISSIONS.items()}
    events = {name: f"Carries {', '.join(fields)}." if fields else "The snapshot your permissions allow." for name, fields in plugins.EVENTS.items()}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "PrintGuard plugin",
        "description": "The manifest of a PrintGuard plugin. See https://github.com/oliverbravery/PrintGuard/blob/main/docs/plugins.md",
        "type": "object",
        "required": ["id", "version"],
        "additionalProperties": False,
        "properties": {
            "$schema": {"type": "string"},
            "id": {
                "type": "string",
                "pattern": plugins.ID_PATTERN.pattern,
                "description": "Identifies the plugin everywhere, 3 to 40 lowercase letters, digits or hyphens.",
            },
            "name": {"type": "string", "description": "Shown on the panel and in Settings. Defaults to the id."},
            "version": {
                "type": "string",
                "pattern": plugins.VERSION_PATTERN.pattern,
                "description": "Your own version, shown beside the name.",
            },
            "description": {"type": "string", "maxLength": 400, "description": "One line about what it does."},
            "author": {"type": "string", "maxLength": 80},
            "homepage": {"type": "string", "maxLength": 200, "format": "uri"},
            "permissions": {
                "type": "array",
                "uniqueItems": True,
                "description": "What it asks for at install. Anything not granted is refused at the sandbox edge.",
                "items": {"anyOf": choices(permissions)},
            },
            "surfaces": {
                "type": "array",
                "uniqueItems": True,
                "description": "Where plugin.js draws. Defaults to a dashboard panel.",
                "items": {"anyOf": choices({name: SURFACE_HELP[name] for name in plugins.SURFACES})},
            },
            "platforms": {
                "type": "array",
                "uniqueItems": True,
                "description": "Where it runs. Leave it out for everywhere, and name a bare platform to cover its variants.",
                "items": {"anyOf": choices(plugins.PLATFORMS)},
            },
            "hosts": {
                "type": "array",
                "uniqueItems": True,
                "description": "The only hosts ctx.http may reach, each a bare hostname.",
                "items": {"type": "string", "pattern": r"^[^/:\s]+$"},
            },
            "events": {
                "type": "array",
                "uniqueItems": True,
                "description": "The engine events that wake worker.js.",
                "items": {"anyOf": choices(events)},
            },
            "tick_s": {
                "type": "number",
                "description": f"Run worker.js this often as well, in seconds. 0, or {plugins.MIN_TICK_S:.0f} at the least.",
                "anyOf": [{"const": 0}, {"minimum": plugins.MIN_TICK_S, "maximum": 86400}],
            },
        },
    }


def main() -> None:
    SCHEMA_FILE.write_text(json.dumps(schema(), indent=2) + "\n")
    print(f"wrote {SCHEMA_FILE}")


if __name__ == "__main__":
    main()
