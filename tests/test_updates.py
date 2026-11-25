"""Update check: GitHub release comparison, filtering, the commands and the desktop app installing its own updates."""

from __future__ import annotations

import asyncio

import pytest
from fakes import FakePlatform, FakeUpdater

from printguard.engine import engine as engine_module
from printguard.engine.engine import Engine


def _release(
    tag: str, body: str = "notes", *, draft: bool = False, prerelease: bool = False, assets: list[str] | None = None
) -> dict:
    return {
        "tag_name": tag,
        "name": tag.lstrip("v"),
        "body": body,
        "html_url": f"https://github.com/o/r/releases/tag/{tag}",
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-06-18T00:00:00Z",
        "assets": [
            {"name": name, "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{name}"}
            for name in assets or []
        ],
    }


def _engine(version: str = "2.1.0", releases: list[dict] | None = None) -> tuple[Engine, FakePlatform]:
    platform = FakePlatform()
    platform.version = version
    platform.releases = releases or []
    return Engine(platform), platform


def _desktop(releases: list[dict] | None = None, settings: dict | None = None) -> tuple[Engine, FakePlatform]:
    """An engine on a desktop app that installs its own updates, saved before with ``settings`` if given."""
    engine, platform = _engine(releases=releases)
    platform.updater = FakeUpdater()
    if settings is not None:
        platform.state = {"settings": settings}
    return engine, platform


async def _check(engine: Engine) -> dict:
    events = await engine.request({"cmd": "update.check"})
    return next(e for e in events if e["event"] == "state")["update"]


async def test_reports_stable_releases_newest_first() -> None:
    engine, platform = _engine(
        version="2.1.0",
        releases=[
            _release("v2.1.0"),
            _release("v2.2.0", "two-two"),
            _release("v2.3.0", "two-three"),
            _release("v2.4.0", draft=True),
            _release("v2.5.0-rc1", prerelease=True),
            _release("v2.6.0rc2"),  # prerelease by version, GitHub flag unset
        ],
    )
    update = await _check(engine)
    assert update["available"] is True
    assert update["latest"] == "2.3.0"
    assert [r["version"] for r in engine.releases] == ["2.3.0", "2.2.0", "2.1.0"]
    assert engine.releases[0]["notes"] == "two-three"
    assert engine.releases[0]["files_url"] == "https://github.com/o/r/blob/v2.3.0/"
    assert ("GET", "https://api.github.com/repos/o/r/releases") in platform.http_calls


async def test_history_is_served_on_demand_not_in_every_snapshot() -> None:
    engine, platform = _engine(version="2.3.0", releases=[_release("v2.2.0"), _release("v2.3.0", "three")])
    events = await engine.request({"cmd": "update.releases"})
    served = next(e for e in events if e["event"] == "releases")["releases"]
    assert [r["version"] for r in served] == ["2.3.0", "2.2.0"]
    assert "releases" not in engine.state_event()["update"]

    calls = len(platform.http_calls)
    await engine.request({"cmd": "update.releases"})
    assert len(platform.http_calls) == calls, "a second request must serve what was already fetched"


async def test_history_does_not_reach_out_with_the_daily_check_off() -> None:
    engine, platform = _engine(version="2.3.0", releases=[_release("v2.3.0")])
    engine.settings["update_check"] = False
    events = await engine.request({"cmd": "update.releases"})
    assert next(e for e in events if e["event"] == "releases")["releases"] == []
    assert platform.http_calls == []

    await engine.request({"cmd": "update.check"})
    events = await engine.request({"cmd": "update.releases"})
    assert [r["version"] for r in next(e for e in events if e["event"] == "releases")["releases"]] == ["2.3.0"]


async def test_a_check_that_fails_at_boot_is_tried_again_well_inside_a_day(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "UPDATE_RETRY_S", 0.05)
    engine, platform = _engine(version="2.1.0", releases=[_release("v2.3.0")])
    platform.responses["https://api.github.com/repos/o/r/releases"] = (503, {})
    await engine.start()
    try:
        await asyncio.sleep(0.02)
        assert engine.update is None
        del platform.responses["https://api.github.com/repos/o/r/releases"]
        await asyncio.sleep(0.1)
        assert engine.update["latest"] == "2.3.0"
    finally:
        await engine.stop()


async def test_up_to_date_reports_no_update() -> None:
    engine, _ = _engine(version="2.3.0", releases=[_release("v2.2.0"), _release("v2.3.0")])
    update = await _check(engine)
    assert update["available"] is False
    assert update["latest"] == "2.3.0"
    assert [r["version"] for r in engine.releases] == ["2.3.0", "2.2.0"]


async def test_desktop_asset_resolves_to_latest_download() -> None:
    releases = [
        _release("v2.2.0", assets=["PrintGuard-macos-arm64.dmg"]),
        _release("v2.3.0", assets=["PrintGuard-macos-arm64.dmg", "PrintGuard-windows-x64.zip"]),
    ]
    engine, platform = _engine(version="2.1.0", releases=releases)
    platform.update_asset = "PrintGuard-macos-arm64.dmg"
    update = await _check(engine)
    assert update["download"] == "https://github.com/o/r/releases/download/v2.3.0/PrintGuard-macos-arm64.dmg"


async def test_no_asset_means_no_download() -> None:
    engine, _ = _engine(version="2.1.0", releases=[_release("v2.3.0", assets=["PrintGuard-macos-arm64.dmg"])])
    update = await _check(engine)
    assert update["download"] is None


async def test_non_web_release_links_are_refused() -> None:
    malicious = _release("v2.3.0")
    malicious["html_url"] = "javascript:alert(1)"
    malicious["assets"] = [{"name": "PrintGuard-macos-arm64.dmg", "browser_download_url": "javascript:alert(2)"}]
    engine, platform = _engine(version="2.1.0", releases=[malicious])
    platform.update_asset = "PrintGuard-macos-arm64.dmg"
    update = await _check(engine)
    assert update["download"] is None
    assert engine.releases[0]["url"] == "https://github.com/o/r/releases/tag/v2.3.0"


async def test_version_and_default_setting_in_state() -> None:
    engine, _ = _engine(version="2.1.0")
    state = engine.state_event()
    assert state["version"] == "2.1.0"
    assert state["update"] is None
    assert state["installs_updates"] is False
    assert engine.settings["update_check"] is True


async def test_a_new_hub_installs_updates_by_itself_and_one_saved_before_keeps_installing_them_by_hand() -> None:
    fresh, _ = _desktop()
    await fresh.start()
    saved, _ = _desktop(settings={"theme": "dark"})
    await saved.start()
    try:
        assert fresh.settings["auto_update"] is True
        assert saved.settings["auto_update"] is False
    finally:
        await fresh.stop()
        await saved.stop()


async def test_a_newer_release_is_downloaded_after_the_check_and_offered_to_restart_into() -> None:
    engine, platform = _desktop(releases=[_release("v2.3.0")])
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        state = engine.state_event()
        assert platform.updater.downloads == 1
        assert state["installs_updates"] is True
        assert state["update"]["ready"] == "2.3.0"
    finally:
        await engine.stop()


@pytest.mark.parametrize("settings", [{"auto_update": False}, {"auto_update": True, "skipped_version": "2.3.0"}])
async def test_nothing_is_downloaded_with_automatic_installs_off_or_the_release_skipped(settings: dict) -> None:
    engine, platform = _desktop(releases=[_release("v2.3.0")], settings=settings)
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        assert platform.updater.downloads == 0
        assert engine.state_event()["update"]["ready"] is None
    finally:
        await engine.stop()


async def test_skipping_a_downloaded_release_withdraws_it() -> None:
    engine, _ = _desktop(releases=[_release("v2.3.0")])
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        await engine.request({"cmd": "settings.update", "patch": {"skipped_version": "2.3.0"}})
        assert engine.state_event()["update"]["ready"] is None
    finally:
        await engine.stop()


async def test_a_download_that_fails_is_warned_of() -> None:
    engine, platform = _desktop(releases=[_release("v2.3.0")])
    platform.updater.failing = True
    events: list[dict] = []
    engine.add_sink(events.append)
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        assert any(e["event"] == "warning" and "v2.3.0 could not be downloaded" in e["message"] for e in events)
        assert engine.state_event()["update"]["ready"] is None
    finally:
        await engine.stop()


async def test_a_downloaded_release_installs_once_by_itself_when_no_monitor_is_watching(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.01)
    monkeypatch.setattr(engine_module, "UPDATE_INSTALL_GRACE_S", 0.2)
    engine, platform = _desktop(releases=[_release("v2.3.0")])
    await engine.start()
    try:
        await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 5}})
        camera_id = engine.cameras.values()[0].id
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": "m", "camera_id": camera_id}})
        await asyncio.sleep(0.4)
        assert platform.updater.installs == 0, "a monitor with no printer linked is always watching"

        await engine.handle({"cmd": "monitor.update", "id": next(iter(engine.monitors)), "patch": {"enabled": False}})
        await asyncio.sleep(0.1)
        assert platform.updater.installs == 1
    finally:
        await engine.stop()


async def test_a_downloaded_release_waits_for_the_user_before_installing_by_itself(monkeypatch) -> None:
    monkeypatch.setattr(engine_module, "STATE_TICK_S", 0.01)
    engine, platform = _desktop(releases=[_release("v2.3.0")])
    await engine.start()
    try:
        await asyncio.sleep(0.1)
        assert engine.state_event()["update"]["ready"] == "2.3.0"
        assert platform.updater.installs == 0
    finally:
        await engine.stop()


async def test_installing_now_downloads_the_release_first_when_the_background_has_not() -> None:
    engine, platform = _desktop(settings={"auto_update": False})
    await engine.request({"cmd": "update.install"})
    assert (platform.updater.downloads, platform.updater.installs) == (1, 1)


async def test_installing_is_refused_where_the_app_cannot_or_with_nothing_newer() -> None:
    container, _ = _engine()
    with pytest.raises(RuntimeError, match="updated outside the app"):
        await container.request({"cmd": "update.install"})
    desktop, platform = _desktop()
    platform.updater.version = None
    with pytest.raises(RuntimeError, match="no newer release"):
        await desktop.request({"cmd": "update.install"})
    assert platform.updater.installs == 0


async def test_turning_automatic_installs_on_downloads_a_release_already_found() -> None:
    engine, platform = _desktop(releases=[_release("v2.3.0")], settings={"auto_update": False})
    await engine.start()
    try:
        await asyncio.sleep(0.05)
        assert platform.updater.downloads == 0
        await engine.request({"cmd": "settings.update", "patch": {"auto_update": True}})
        await asyncio.sleep(0.05)
        assert platform.updater.downloads == 1
        assert engine.state_event()["update"]["ready"] == "2.3.0"
    finally:
        await engine.stop()
