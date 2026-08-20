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

from printguard.engine import plugins, urls  # noqa: E402

HERE = Path(__file__).parent
SCHEMA_FILE = HERE / "plugin.schema.json"
SCHEMA_URL = "https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/plugin.schema.json"

SURFACE_HELP = {
    "panel": "A panel of its own on the dashboard.",
    "monitor": "Drawn on every monitor tile, once per monitor.",
    "settings": "Drawn in every monitor's settings, once per monitor.",
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
                "description": "What it asks for. The user accepts all of it or none of it before the plugin can be enabled.",
                "items": {"anyOf": choices(permissions)},
            },
            "reasons": {
                "type": "object",
                "description": "Why it wants each permission, in your own words, shown when the user is asked to accept them. One line per permission, and every one it asks for needs one.",
                "propertyNames": {"enum": list(permissions)},
                "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 200},
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
            "assets": {
                "type": "array",
                "uniqueItems": True,
                "description": "Files it ships beside its code, each named here and sitting next to plugin.js.",
                "items": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]{0,39}\.(" + "|".join(sorted(plugins.ASSET_TYPES)) + ")$"},
            },
            "urls": {
                "type": "array",
                "uniqueItems": True,
                "description": "The only addresses ctx.http and ctx.socket may reach, each a match pattern of scheme://host/path. Naming a private or loopback address needs the net:local permission as well as net.",
                "items": {"type": "string", "pattern": urls.PATTERN.pattern},
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
