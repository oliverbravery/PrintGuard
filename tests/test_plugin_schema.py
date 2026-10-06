"""The manifest schema an editor reads, held to the engine it describes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))

import schema as generator  # noqa: E402

from printguard.engine import plugins  # noqa: E402


def test_the_committed_schema_matches_the_tables() -> None:
    """Rerun `uv run python plugins/schema.py` and commit what it writes."""
    assert json.loads(generator.SCHEMA_FILE.read_text()) == generator.schema()


def test_the_schema_names_every_field_a_manifest_carries() -> None:
    manifest = plugins.sanitise_manifest({"id": "demo-plugin", "version": "1.0.0"})

    assert set(generator.schema()["properties"]) == {"$schema", *manifest}


def patterns(node: object) -> list[str]:
    if isinstance(node, dict):
        found = [node["pattern"]] if isinstance(node.get("pattern"), str) else []
        return found + [pattern for value in node.values() for pattern in patterns(value)]
    if isinstance(node, list):
        return [pattern for value in node for pattern in patterns(value)]
    return []


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_every_pattern_in_the_schema_compiles_as_an_ecmascript_regex() -> None:
    """An editor evaluates `pattern` in JavaScript, where Python's named groups are a syntax error."""
    script = "for (const p of JSON.parse(require('fs').readFileSync(0, 'utf8'))) new RegExp(p, 'u');"
    found = patterns(generator.schema())

    assert any("scheme" in pattern or "http" in pattern for pattern in found)
    subprocess.run(["node", "-e", script], input=json.dumps(found), text=True, check=True, capture_output=True)
