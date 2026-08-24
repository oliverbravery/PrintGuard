"""The match patterns a plugin's network grant is written in."""

from __future__ import annotations

import pytest

from printguard.engine import urls

MATCHING = [
    ("https://api.spotify.com/v1/me/player", "https://api.spotify.com/v1/me/player"),
    ("https://*.spotify.com/*", "https://api.spotify.com/v1/me?market=GB"),
    ("https://*.spotify.com/*", "https://spotify.com/"),
    ("*://example.com/*", "http://example.com/a"),
    ("*://example.com/*", "https://example.com/a"),
    ("https://example.com/feed/*", "https://example.com/feed/today.json"),
    ("wss://ha.local/api/*", "wss://ha.local/api/websocket"),
    ("http://192.168.1.50:8080/*", "http://192.168.1.50:8080/status"),
    ("https://example.com/*", "https://example.com:443/a"),
    ("*://*/*", "https://anything.at.all/x"),
]

REFUSED = [
    ("https://api.spotify.com/v1/me/player", "https://api.spotify.com/v1/me"),
    ("https://*.spotify.com/*", "https://spotify.com.evil.test/x"),
    ("https://*.spotify.com/*", "http://api.spotify.com/x"),
    ("*://example.com/*", "wss://example.com/a"),
    ("https://example.com/feed/*", "https://example.com/other"),
    ("http://192.168.1.50:8080/*", "http://192.168.1.50/status"),
    ("https://example.com/*", "https://sub.example.com/a"),
    ("*://*/*", "rtsp://camera.local/stream"),
]


@pytest.mark.parametrize("pattern,url", MATCHING)
def test_a_pattern_covers_what_it_should(pattern: str, url: str) -> None:
    assert urls.matches(pattern, url)


@pytest.mark.parametrize("pattern,url", REFUSED)
def test_a_pattern_covers_nothing_else(pattern: str, url: str) -> None:
    assert not urls.matches(pattern, url)


def test_malformed_patterns_are_refused_rather_than_ignored() -> None:
    for bad in ("example.com", "https://example.com", "ftp://example.com/*", "https:///*", "https://*example.com/*"):
        with pytest.raises(ValueError, match="match pattern"):
            urls.sanitise([bad])


def test_a_pattern_reaching_this_network_is_told_apart_from_one_that_does_not() -> None:
    local = ["http://192.168.1.50/*", "http://localhost:8000/*", "wss://ha.local/*", "*://*/*", "http://[::1]/*"]
    public = ["https://api.spotify.com/*", "https://*.github.com/*"]

    assert all(urls.reaches_local(pattern) for pattern in local)
    assert not any(urls.reaches_local(pattern) for pattern in public)


def test_a_public_name_pointing_at_a_private_address_counts_as_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """The literal says nothing, so the answer decides."""
    monkeypatch.setattr(urls.socket, "getaddrinfo", lambda *_: [(2, 1, 6, "", ("10.0.0.5", 0))])

    assert urls.resolves_local("https://looks-public.example/x")


def test_a_name_that_will_not_resolve_is_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urls.socket, "getaddrinfo", lambda *_: (_ for _ in ()).throw(OSError()))

    assert not urls.resolves_local("https://nowhere.example/x")


def test_a_pattern_reads_back_in_words() -> None:
    assert urls.phrase("https://*.spotify.com/*") == "anything on spotify.com and its subdomains"
    assert urls.phrase("https://api.spotify.com/v1/me/player") == "/v1/me/player on api.spotify.com"
    assert urls.phrase("*://*/*") == "anything on any address at all"
    assert urls.phrase("http://192.168.1.50:8080/*") == "anything on 192.168.1.50 on port 8080"
