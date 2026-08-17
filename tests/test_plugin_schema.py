"""The manifest schema an editor reads, held to the engine it describes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))

import schema as generator  # noqa: E402

from printguard.engine import plugins  # noqa: E402


def test_the_committed_schema_matches_the_tables() -> None:
    """Rerun `uv run python plugins/schema.py` and commit what it writes."""
    assert json.loads(generator.SCHEMA_FILE.read_text()) == generator.schema()


def test_the_schema_names_every_field_a_manifest_carries() -> None:
    manifest = plugins.sanitise_manifest({"id": "demo-plugin", "version": "1.0.0"})

    assert set(generator.schema()["properties"]) == {"$schema", *manifest}
