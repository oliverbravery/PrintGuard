"""The desktop app's launch decisions: which copy keeps running, what it registers for login and what it waits for."""

from __future__ import annotations

import errno
import sys
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from printguard.server import desktop

THIS_HUB = {"ok": True, "version": "1.2.3"}
FOREIGN_PAGE = {"hello": "from some other program"}
NEVER_ABANDONED = SimpleNamespace(wait=lambda seconds: False)


def _answering(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    monkeypatch.setattr(desktop, "_health", lambda port: payload)


def test_waiting_ends_when_a_hub_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    _answering(monkeypatch, THIS_HUB)

    assert desktop._wait_until_answering(8000, NEVER_ABANDONED)


def test_waiting_does_not_take_another_program_for_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """A program on [::1] answers localhost with its own page, which the window would then show."""
    _answering(monkeypatch, FOREIGN_PAGE)

    assert not desktop._wait_until_answering(8000, NEVER_ABANDONED, timeout=0)


def test_waiting_stops_when_abandoned() -> None:
    abandoned = threading.Event()
    abandoned.set()

    assert not desktop._wait_until_answering(8000, abandoned)


@pytest.fixture
def launch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SimpleNamespace:
    """Runs ``main`` up to the point it would build the tray, recording what it opened."""
    launched = SimpleNamespace(browser=[], windows=[], autostart_refreshed=[])
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "printguard.log"))
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setattr(desktop, "_configure_environment", lambda: None)
    monkeypatch.setattr(desktop, "_set_windows_app_id", lambda: None)
    monkeypatch.setattr(desktop.logs, "setup_from_env", lambda: None)
    monkeypatch.setattr(desktop.webbrowser, "open", launched.browser.append)
    monkeypatch.setattr(desktop, "_refresh_autostart", lambda: launched.autostart_refreshed.append(True))
    monkeypatch.setattr(desktop, "_Window", lambda **contents: launched.windows.append(contents) or sys.exit("tray reached"))
    return launched


def _held_port(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(port: int) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(desktop, "_listening_socket", refuse)


def test_a_second_copy_opens_the_browser_instead_of_starting(monkeypatch: pytest.MonkeyPatch, launch) -> None:
    monkeypatch.setattr(desktop, "_hub_running", lambda port: True)

    desktop.main()

    assert launch.browser == [desktop._webview_url(8123)]
    assert launch.windows == []
    assert launch.autostart_refreshed == []


def test_a_second_copy_opens_the_browser_while_the_first_is_still_starting(
    monkeypatch: pytest.MonkeyPatch, launch
) -> None:
    """The first copy holds the port from its bind but only answers once its startup is done."""
    monkeypatch.setattr(desktop, "_hub_running", lambda port: False)
    _held_port(monkeypatch)
    waited: list[tuple[int, float | None]] = []
    monkeypatch.setattr(
        desktop, "_wait_until_answering", lambda port, abandoned, timeout=None: waited.append((port, timeout)) or True
    )

    desktop.main()

    assert waited == [(8123, desktop.READY_TIMEOUT_S)]
    assert launch.browser == [desktop._webview_url(8123)]
    assert launch.windows == []
    assert launch.autostart_refreshed == []


def test_a_port_held_by_another_program_shows_the_failure_page(monkeypatch: pytest.MonkeyPatch, launch) -> None:
    monkeypatch.setattr(desktop, "_hub_running", lambda port: False)
    _held_port(monkeypatch)
    monkeypatch.setattr(desktop, "_wait_until_answering", lambda port, abandoned, timeout=None: False)
    monkeypatch.setattr(desktop, "_failure_page", lambda: "failure")

    with pytest.raises(SystemExit, match="tray reached"):
        desktop.main()

    assert launch.browser == []
    assert launch.windows == [{"html": "failure"}]


@pytest.mark.parametrize(
    ("frozen", "executable", "registered", "rewritten"),
    [
        (True, "/Applications/PrintGuard.app/Contents/MacOS/PrintGuard", True, True),
        (True, "C:\\Users\\me\\PrintGuard\\PrintGuard.exe", True, True),
        (True, "/Applications/PrintGuard.app/Contents/MacOS/PrintGuard", False, False),
        (True, "/Volumes/PrintGuard/PrintGuard.app/Contents/MacOS/PrintGuard", True, False),
        (True, "/private/var/folders/x/AppTranslocation/1/d/PrintGuard.app/Contents/MacOS/PrintGuard", True, False),
        (False, "/Users/me/printguard/.venv/bin/python", True, False),
    ],
)
def test_only_the_installed_app_takes_over_the_login_entry(
    monkeypatch: pytest.MonkeyPatch, frozen: bool, executable: str, registered: bool, rewritten: bool
) -> None:
    writes: list[bool] = []
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(desktop, "_autostart_enabled", lambda: registered)
    monkeypatch.setattr(desktop, "_set_autostart", writes.append)

    desktop._refresh_autostart()

    assert writes == ([True] if rewritten else [])


def test_reopening_the_running_app_opens_its_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS sends a reopen request to a running app instead of starting a second copy."""

    class NSObject:
        @classmethod
        def alloc(cls) -> type:
            return cls

        @classmethod
        def init(cls) -> Any:
            return object.__new__(cls)

    delegates: list[Any] = []
    application = SimpleNamespace(setDelegate_=delegates.append)
    monkeypatch.setitem(
        sys.modules,
        "AppKit",
        SimpleNamespace(NSObject=NSObject, NSApplication=SimpleNamespace(sharedApplication=lambda: application)),
    )
    opened: list[bool] = []

    returned = desktop._reopen_from_finder(SimpleNamespace(open=lambda: opened.append(True)))

    assert delegates == [returned]
    assert returned.applicationShouldHandleReopen_hasVisibleWindows_(application, False) is True
    assert opened == [True]
