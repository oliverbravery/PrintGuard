"""The manifest schema an editor reads, held to the engine it describes."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))

import schema as generator  # noqa: E402

from printguard.engine import plugins, urls  # noqa: E402


def test_the_committed_schema_matches_the_tables() -> None:
    """Rerun `uv run python plugins/schema.py` and commit what it writes."""
    assert json.loads(generator.SCHEMA_FILE.read_text()) == generator.schema()


def test_the_schema_names_every_field_a_manifest_carries() -> None:
    manifest = plugins.sanitise_manifest({"id": "demo-plugin", "version": "1.0.0"})

    assert set(generator.schema()["properties"]) == {"$schema", *manifest}


@pytest.mark.parametrize(
    "name",
    ["tick.txt", "a.png", f"{'a' * 36}.png", f"{'a' * 37}.png", f"{'a' * 40}.png", "horn.mp3", "Horn.mp3", "-horn.mp3", "horn", "horn.svg", "sounds/horn.mp3", "a.b_c-d.json"],
)
def test_the_schema_takes_the_asset_names_the_engine_does(name: str) -> None:
    """It allowed 40 characters before the extension, where the engine caps the whole name at 40."""
    pattern = generator.schema()["properties"]["assets"]["items"]["pattern"]

    assert bool(re.search(pattern, name)) == (plugins.asset_type(name) is not None)


@pytest.mark.parametrize(
    "pattern",
    [
        "https://api.example.com/v1/*",
        "HTTPS://API.Example.com/V1/*",
        "Wss://*.Example.com:8443/feed",
        "rtsps://[FE80::1]/stream",
        "*://*/*",
        "ftp://example.com/*",
        "https://example.com",
        "https://exa mple.com/*",
        "https://*example.com/*",
    ],
)
def test_the_schema_takes_the_address_patterns_the_engine_does(pattern: str) -> None:
    """It was lowercase only, where the engine reads the scheme and host in any case."""
    assert bool(re.search(generator.schema()["properties"]["urls"]["items"]["pattern"], pattern)) == (urls.parse(pattern) is not None)


def test_the_schema_stops_a_name_and_the_scopes_where_the_engine_cuts_them() -> None:
    properties = generator.schema()["properties"]
    sign_in = {"authorize_url": "https://auth.example.com/authorize", "token_url": "https://auth.example.com/token", "scopes": [f"scope-{n}" for n in range(50)]}
    manifest = plugins.sanitise_manifest({"id": "demo-plugin", "version": "1.0.0", "name": "n" * 500, "permissions": ["oauth"], "reasons": {"oauth": "to sign in"}, "oauth": sign_in})

    assert len(manifest["name"]) == properties["name"]["maxLength"]
    assert len(manifest["oauth"]["scopes"]) == properties["oauth"]["properties"]["scopes"]["maxItems"]


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
