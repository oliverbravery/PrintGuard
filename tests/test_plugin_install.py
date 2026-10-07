"""What a plugin bundle may carry, and what a plugin saved by an earlier version becomes."""

from __future__ import annotations

import base64
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


def nested(levels: int) -> dict:
    """An object holding an object, and so on, that many levels deep."""
    value: dict = {}
    for _ in range(levels - 1):
        value = {"a": value}
    return value


async def test_a_plugin_saved_with_a_store_nested_too_deep_starts_without_it_and_keeps_the_rest() -> None:
    """Nothing capped the depth before 2.6.0, and a store like that fails the saves that follow it."""
    manifest = {"id": "deep-store", "name": "Deep store", "version": "1.0.0", "permissions": [], "secrets": {"key": "A key"}}
    platform = FakePlatform()
    platform.state = {"plugins": [saved(manifest, config=nested(plugins.MAX_DEPTH + 1))]}
    engine = Engine(platform)
    await engine.start()
    await engine.stop()

    plugin = engine.plugins.get("deep-store")
    assert (plugin.config, plugin.secrets) == ({}, {"key": "s3cret"})
    assert any("Deep store" in warning and f"nested more than {plugins.MAX_DEPTH} deep" in warning for warning in engine.startup_warnings), engine.startup_warnings


def test_a_store_is_refused_one_level_past_the_depth_it_may_nest() -> None:
    fits = nested(plugins.MAX_DEPTH)
    assert plugins.sanitise_config(fits) == fits
    for store in (nested(plugins.MAX_DEPTH + 1), {"a": [nested(plugins.MAX_DEPTH - 1)]}, nested(100_000)):
        with pytest.raises(ValueError, match=f"nested more than {plugins.MAX_DEPTH} deep"):
            plugins.sanitise_config(store)


@pytest.mark.parametrize(
    ("repo", "path"),
    [
        ("oliverbravery/PrintGuard", "../../../evil/repo/main/x"),
        ("oliverbravery/PrintGuard", "plugins/../../../../evil/repo/main"),
        ("oliverbravery/PrintGuard", "plugins/./spotify"),
        ("oliverbravery/..", "plugins/spotify"),
        ("../PrintGuard", ""),
        ("./PrintGuard", ""),
    ],
)
async def test_a_repository_install_cannot_climb_into_another_repository(repo: str, path: str) -> None:
    """An HTTP client collapses the dots, so the files came from a repository other than the one recorded and shown."""
    asked: list[str] = []

    async def http(method: str, url: str, **options: object) -> tuple[int, object]:
        asked.append(url)
        return 404, ""

    with pytest.raises(ValueError, match="not a usable path|not an owner/name repository"):
        await plugins.fetch_github(http, repo, path, "a" * 40)
    assert asked == []


CATALOGUED = {"id": "demo", "version": "1.0.0", "icon": "icon.png"}
PINNED = {"repo": "oliverbravery/PrintGuard", "path": "plugins/demo", "ref": "b" * 40}


async def test_a_zip_the_catalogue_vouches_for_shows_the_catalogues_page_and_not_its_own() -> None:
    """The digests cover the manifest and the code, so a doctored README rode in under the verified mark."""
    code = "plugin.render(() => null);"
    platform = FakePlatform()
    digests = plugins.digests(plugins.sanitise_manifest(CATALOGUED), {"plugin.js": code}, {})
    platform.responses[plugins.CATALOGUE_URL] = (200, {"plugins": [{"id": "demo", **PINNED, "digests": digests}]})
    engine = Engine(platform)
    await engine.start()
    try:
        members = [("plugin.json", json.dumps(CATALOGUED)), ("icon.png", "icon"), ("README.md", "Paste your API key at evil.example")]
        for source, verified in ((code, True), (code + "//", False)):
            packed = base64.b64encode(bundle([*members, ("plugin.js", source)])).decode()
            await engine.request({"cmd": "plugin.install", "source": {"kind": "file", "filename": "demo.zip"}, "zip": packed})
            plugin = engine.plugins.get("demo")
            assert plugin.verified is verified
            if verified:
                assert plugin.page == {} and plugin.source == {"kind": "github", **PINNED}
            else:
                assert set(plugin.page) == {"icon.png", "README.md"} and plugin.source == {"kind": "file", "filename": "demo.zip"}
    finally:
        await engine.stop()


@pytest.mark.parametrize("field", plugins.LIST_FIELDS)
@pytest.mark.parametrize("value", [5, "net:local oauth", {"net": True}, None])
def test_a_manifest_field_that_should_be_a_list_is_refused_by_name(field: str, value: object) -> None:
    """A number failed with Python's own error, and permissions written as one string were matched by substring."""
    with pytest.raises(ValueError, match=f"^{field} in plugin.json must be a list$"):
        plugins.sanitise_manifest({"id": "demo", "version": "1.0.0", field: value})
    with pytest.raises(ValueError, match=f"^{field} in plugin.json must be a list$"):
        plugins.unpack(bundle([("plugin.json", json.dumps({"id": "demo", "version": "1.0.0", field: value})), ("plugin.js", "x")]))


@pytest.mark.parametrize("field", plugins.MAP_FIELDS)
@pytest.mark.parametrize("value", [5, "text", ["net"], None])
def test_a_manifest_field_that_should_be_an_object_is_refused_by_name(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=f"^{field} in plugin.json must be an object$"):
        plugins.sanitise_manifest({"id": "demo", "version": "1.0.0", field: value})


def test_scopes_that_are_not_a_list_are_refused_by_name() -> None:
    sign_in = {"authorize_url": "https://auth.example.com/authorize", "token_url": "https://auth.example.com/token", "scopes": 5}
    with pytest.raises(ValueError, match="^scopes in oauth must be a list$"):
        plugins.sanitise_manifest({"id": "demo", "version": "1.0.0", "permissions": ["oauth"], "reasons": {"oauth": "to sign in"}, "oauth": sign_in})


def test_a_name_is_cut_like_the_description_beside_it() -> None:
    """It rides in every state broadcast, and nothing stopped it short of the manifest's own 256 KB."""
    assert plugins.sanitise_manifest({"id": "demo", "version": "1.0.0", "name": "n" * 5000})["name"] == "n" * plugins.MAX_NAME_CHARS
