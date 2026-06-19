"""Update check: GitHub release comparison, filtering and the command."""

from __future__ import annotations

import pytest
from fakes import FakePlatform

from printguard.engine.engine import Engine


def _release(tag: str, body: str = "notes", *, draft: bool = False, prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": tag.lstrip("v"),
        "body": body,
        "html_url": f"https://github.com/o/r/releases/tag/{tag}",
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-06-18T00:00:00Z",
    }


def _engine(version: str = "2.1.0", releases: list[dict] | None = None) -> tuple[Engine, FakePlatform]:
    platform = FakePlatform()
    platform.version = version
    platform.update_repo = "o/r"
    platform.releases = releases or []
    return Engine(platform), platform


async def _check(engine: Engine) -> dict:
    events = await engine.request({"cmd": "update.check"})
    return next(e for e in events if e["event"] == "state")["update"]


async def test_reports_only_newer_stable_releases_newest_first() -> None:
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
    assert [r["version"] for r in update["releases"]] == ["2.3.0", "2.2.0"]
    assert update["releases"][0]["notes"] == "two-three"
    assert ("GET", "https://api.github.com/repos/o/r/releases") in platform.http_calls


async def test_up_to_date_reports_no_update() -> None:
    engine, _ = _engine(version="2.3.0", releases=[_release("v2.2.0"), _release("v2.3.0")])
    update = await _check(engine)
    assert update["available"] is False
    assert update["latest"] == "2.3.0"
    assert update["releases"] == []


async def test_check_errors_when_repo_unset() -> None:
    engine = Engine(FakePlatform())  # update_repo defaults to None (local mode)
    with pytest.raises(RuntimeError, match="not available"):
        await engine.request({"cmd": "update.check"})


async def test_version_and_default_setting_in_state() -> None:
    engine, _ = _engine(version="2.1.0")
    state = engine.state_event()
    assert state["version"] == "2.1.0"
    assert state["update"] is None
    assert engine.settings["update_check"] is True
