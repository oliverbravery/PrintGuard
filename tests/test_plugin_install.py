"""What a plugin bundle may carry, and what a plugin saved by an earlier version becomes."""

from __future__ import annotations

import io
import json
import warnings
import zipfile

import pytest
from fakes import FakePlatform

from printguard.engine import plugins
from printguard.engine.engine import Engine

MANIFEST = {"id": "demo", "version": "1.0.0", "assets": ["tick.txt"], "icon": "icon.png"}


def bundle(members: list[tuple[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, content in members:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_a_zip_installs_the_files_beside_its_manifest_and_not_one_that_shares_a_name_deeper_in() -> None:
    """A file was taken by its name from anywhere in the archive, so a worker in an examples folder replaced the plugin's own."""
    manifest, sources, assets, page = plugins.unpack(
        bundle(
            [
                ("demo/plugin.json", json.dumps(MANIFEST)),
                ("demo/panel.html", "<p>mine</p>"),
                ("demo/docs/examples/deep/worker.js", "plugin.on('alert', () => ctx.command({}))"),
                ("demo/docs/examples/deep/tick.txt", "theirs"),
                ("demo/docs/icon.png", "theirs"),
            ]
        )
    )

    assert sources == {"panel.html": "<p>mine</p>"}
    assert assets == {} and page == {}


def test_a_zip_reads_its_files_from_the_folder_that_holds_the_manifest() -> None:
    _, sources, assets, page = plugins.unpack(
        bundle(
            [
                ("demo/plugin.json", json.dumps(MANIFEST)),
                ("demo/worker.js", "mine"),
                ("demo/tick.txt", "tick"),
                ("demo/icon.png", "icon"),
                ("worker.js", "outside"),
                ("tick.txt", "outside"),
            ]
        )
    )

    assert sources == {"worker.js": "mine"} and assets == {"tick.txt": b"tick"} and page == {"icon.png": b"icon"}


def test_a_zip_holding_two_plugins_is_refused_rather_than_mixed() -> None:
    with pytest.raises(ValueError, match="more than one plugin.json"):
        plugins.unpack(
            bundle(
                [
                    ("a/plugin.json", json.dumps({**MANIFEST, "id": "plugin-a"})),
                    ("a/panel.html", "a"),
                    ("b/plugin.json", json.dumps({**MANIFEST, "id": "plugin-b"})),
                    ("b/worker.js", "b"),
                ]
            )
        )


def test_a_zip_listing_a_file_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="more than once"):
        plugins.unpack(bundle([("plugin.json", json.dumps(MANIFEST)), ("worker.js", "first"), ("worker.js", "second")]))


SAVED_BY_2_5 = {"sources": {"plugin.js": "plugin.render(() => null);"}, "digests": {}, "source": {"kind": "file"}, "installed": 1.0}


def saved(manifest: dict, **fields: object) -> dict:
    return {"id": manifest["id"], "manifest": manifest, "granted": manifest["permissions"], "config": {"kept": 1}, "secrets": {"key": "s3cret"}, **SAVED_BY_2_5, **fields}


@pytest.mark.parametrize("pattern", ["http://octopi.home.arpa/*", "http://127.1/*", "http://*.local/*", "ws://[64:ff9b::c0a8:101]/*"])
async def test_a_plugin_saved_before_the_local_network_had_its_own_permission_stays_installed_and_waits_for_it(pattern: str) -> None:
    """It was dropped with its data and credentials, and the changelog only named the plain http sign-in."""
    manifest = {"id": "printer-peek", "name": "Printer peek", "version": "1.0.0", "permissions": ["net"], "reasons": {"net": "reads my printer"}, "urls": [pattern], "secrets": {"key": "A key"}}
    platform = FakePlatform()
    platform.state = {"plugins": [saved(manifest)]}
    engine = Engine(platform)
    await engine.start()
    try:
        plugin = engine.plugins.get("printer-peek")
        assert plugin is not None, "the plugin was removed with what it had stored"
        assert (plugin.config, plugin.secrets, plugin.granted) == ({"kept": 1}, {"key": "s3cret"}, ["net"])
        assert not plugin.enabled and "net:local" in plugin.manifest["permissions"]
        assert any("Printer peek now needs Reach your own network" in warning for warning in engine.startup_warnings), engine.startup_warnings

        with pytest.raises(RuntimeError, match="have not been accepted"):
            await engine.request({"cmd": "plugin.update", "id": "printer-peek", "patch": {"enabled": True}})
        await engine.request({"cmd": "plugin.update", "id": "printer-peek", "patch": {"granted": ["net", "net:local"], "enabled": True}})
        assert engine.plugins.get("printer-peek").enabled
    finally:
        await engine.stop()


async def test_a_plugin_saved_with_a_plain_http_sign_in_is_still_removed_and_the_warning_names_it() -> None:
    """No permission makes that sign-in readable, so the removal the changelog describes stands."""
    manifest = {
        "id": "old-signin",
        "version": "1.0.0",
        "permissions": ["net", "oauth"],
        "reasons": {"net": "a", "oauth": "b"},
        "urls": ["https://api.example.com/*"],
        "oauth": {"authorize_url": "http://auth.example.com/authorize", "token_url": "http://auth.example.com/token"},
    }
    platform = FakePlatform()
    platform.state = {"plugins": [saved(manifest)]}
    engine = Engine(platform)
    await engine.start()
    await engine.stop()

    assert engine.plugins.get("old-signin") is None
    assert any("old-signin" in warning and "https" in warning for warning in engine.startup_warnings), engine.startup_warnings
