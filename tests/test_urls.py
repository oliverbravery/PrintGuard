"""The match patterns a plugin's network grant is written in."""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
import time
from pathlib import Path

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
    ("http://[fd00::1]/*", "http://[fd00::1]/status"),
    ("http://[fd00::1]:8080/*", "http://[FD00::1]:8080/status"),
    ("https://example.com/v1/*", "https://example.com/v1/a..b/.hidden"),
    ("https://api.telegram.org/bot*/sendMessage", "https://api.telegram.org/bot123:abc/sendMessage"),
    ("HTTPS://API.Telegram.org/bot*/sendMessage", "https://API.telegram.ORG/bot1/sendMessage"),
    ("https://example.com/*/jobs/*/cancel", "https://example.com/v1/jobs/7/jobs/8/cancel"),
    ("https://example.com/a*a", "https://example.com/aa"),
    ("https://example.com/*.json*", "https://example.com/feed.json?page=2"),
    ("https://api.telegram.org/bot*/sendMessage", "https://api.telegram.org/bot1/sendMessage?chat_id=5"),
    ("https://example.com/search?q=*", "https://example.com/search?q=benchy"),
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
    ("http://[fd00::1]/*", "http://[fd00::2]/status"),
    ("https://example.com/v1/*", "https://example.com/v1/../admin"),
    ("https://example.com/v1/*", "https://example.com/v1/%2e%2e/admin"),
    ("https://example.com/v1/*", "https://example.com/v1/.%2E/admin"),
    ("https://example.com/v1/*", "https://example.com/v1/a/./../../admin"),
    ("https://example.com/v1/*", "https://example.com/v1/..\\admin"),
    ("https://example.com/v1/*", "https://example.com/v1/.."),
    ("https://api.telegram.org/bot*/sendMessage", "https://api.telegram.org/bot1/sendmessage"),
    ("https://example.com/a*a", "https://example.com/a"),
    ("https://example.com/*/jobs/*/cancel", "https://example.com/v1/jobs/cancel"),
    ("https://example.com/v1/*/a", "https://example.com/v1/b/ab"),
    ("https://api.telegram.org/bot*/sendMessage", "https://api.telegram.org/bot1/getUpdates?x=/sendMessage"),
    ("https://example.com/*/cancel", "https://example.com/v1/delete?then=/cancel"),
    ("https://example.com/search?q=*", "https://example.com/search?page=2"),
]


@pytest.mark.parametrize("pattern,url", MATCHING)
def test_a_pattern_covers_what_it_should(pattern: str, url: str) -> None:
    assert urls.matches(pattern, url)


@pytest.mark.parametrize("pattern,url", REFUSED)
def test_a_pattern_covers_nothing_else(pattern: str, url: str) -> None:
    assert not urls.matches(pattern, url)


def test_a_pattern_keeps_the_case_of_its_path_and_drops_that_of_its_host() -> None:
    assert urls.sanitise(["HTTPS://API.Telegram.org/bot*/sendMessage"]) == ["https://api.telegram.org/bot*/sendMessage"]


def test_a_pattern_full_of_wildcards_is_matched_as_fast_as_any_other() -> None:
    """The match runs on the event loop, so a slow one stops detection."""
    pattern = "https://example.com/" + "*a" * 24 + "b"
    started = time.perf_counter()

    assert not urls.matches(pattern, "https://example.com/" + "a" * 4000)
    assert urls.matches(pattern, "https://example.com/" + "a" * 4000 + "b")
    assert time.perf_counter() - started < 0.5


def test_malformed_patterns_are_refused_rather_than_ignored() -> None:
    for bad in ("example.com", "https://example.com", "ftp://example.com/*", "https:///*", "https://*example.com/*"):
        with pytest.raises(ValueError, match="match pattern"):
            urls.sanitise([bad])


def test_a_pattern_reaching_this_network_is_told_apart_from_one_that_does_not() -> None:
    local = ["http://192.168.1.50/*", "http://localhost:8000/*", "wss://ha.local/*", "*://*/*", "http://[::1]/*"]
    public = ["https://api.spotify.com/*", "https://*.github.com/*"]

    assert all(urls.reaches_local(pattern) for pattern in local)
    assert not any(urls.reaches_local(pattern) for pattern in public)


WILDCARD_PATTERNS = [
    "http://*.local/*",
    "https://*.lan/*",
    "http://*.home.arpa/*",
    "ws://*.internal/*",
    "http://*.localhost:8000/*",
    "https://*.github.com/*",
    "https://*.example.com/*",
    "http://*.168.1.50/*",
]


@pytest.mark.parametrize("pattern", WILDCARD_PATTERNS[:5])
def test_a_wildcard_over_a_local_suffix_reaches_this_network(pattern: str) -> None:
    assert urls.reaches_local(pattern)


@pytest.mark.parametrize("pattern", WILDCARD_PATTERNS[5:])
def test_a_wildcard_over_a_public_name_does_not(pattern: str) -> None:
    assert not urls.reaches_local(pattern)


@pytest.mark.skipif(shutil.which("node") is None, reason="the dashboard's copy of the rules runs on node")
def test_the_dashboard_sorts_wildcard_patterns_as_the_engine_does() -> None:
    script = "import('./src/urls.ts').then((urls) => console.log(JSON.stringify(JSON.parse(process.argv[1]).map(urls.reachesLocal))))"
    answered = subprocess.run(
        ["node", "-e", script, json.dumps(WILDCARD_PATTERNS)], cwd=Path(__file__).resolve().parent.parent / "web", capture_output=True, text=True, check=True
    )
    assert json.loads(answered.stdout) == [urls.reaches_local(pattern) for pattern in WILDCARD_PATTERNS]


@pytest.mark.parametrize("host", ["2130706433", "127.1", "0x7f.0.0.1", "017700000001", "192.168.257", "0xc0a80132"])
def test_an_address_is_local_however_it_is_spelt(host: str) -> None:
    assert urls.is_local_address(host)
    assert urls.reaches_local(f"http://{host}/*"), "a plugin asked for this network under the public permission"


@pytest.mark.parametrize("host", ["[fec0::1]", "[feff::1]", "[ff02::1]", "[ff0e::1]", "224.0.0.1", "239.255.255.250"])
def test_a_site_local_or_multicast_address_is_local(host: str) -> None:
    """The standard library calls these global, and a connection to one stays on this network."""
    assert urls.is_local_address(host)
    assert urls.reaches_local(f"http://{host}/*"), "a plugin asked for this network under the public permission"


@pytest.mark.parametrize(
    "host", ["[64:ff9b::c0a8:101]", "[64:ff9b::7f00:1]", "[::192.168.1.1]", "[::c0a8:101]", "[::ffff:0:c0a8:101]", "[::ffff:192.168.1.1]", "[::7f00:1]"]
)
def test_an_ipv4_address_inside_an_ipv6_one_is_local_when_the_ipv4_address_is(host: str) -> None:
    """NAT64 and the other embeddings deliver to the IPv4 address, which the standard library calls global."""
    assert urls.is_local_address(host)
    assert "." in host or urls.reaches_local(f"http://{host}/*")


@pytest.mark.parametrize("host", ["[64:ff9b::808:808]", "[::808:808]", "[::ffff:0:808:808]", "[::ffff:8.8.8.8]"])
def test_an_ipv4_address_inside_an_ipv6_one_is_public_when_the_ipv4_address_is(host: str) -> None:
    assert not urls.is_local_address(host)


@pytest.mark.parametrize("host", ["134744072", "8.8.2056", "0x8.8.8.8", "1.1.1.1.1", "example.com"])
def test_an_oddly_spelt_public_address_is_not_local(host: str) -> None:
    assert not urls.is_local_address(host)


def edges() -> list[str]:
    """Hosts either side of every boundary the address rules draw."""
    constants = (ipaddress._IPv4Constants, ipaddress._IPv6Constants)
    networks = [network for family in constants for network in (*family._private_networks, *family._private_networks_exceptions)]
    networks.append(ipaddress._IPv4Constants._public_network)
    networks.extend((*urls.EMBEDDING_IPV4, *urls.UNROUTED))
    hosts = ["2130706433", "127.1", "0x7f.0.0.1", "134744072", "1.1.1.1.1", "localhost", "octopi.local", "example.com", "local"]
    for network in networks:
        first, last = int(network.network_address), int(network.broadcast_address)
        for number in {max(first - 1, 0), first, last, min(last + 1, 2**network.max_prefixlen - 1)}:
            address = ipaddress.ip_address(number) if network.version == 4 else ipaddress.IPv6Address(number)
            hosts.append(str(address) if network.version == 4 else f"[{address}]")
            if network.version == 4:
                hosts.extend(f"[{prefix}{address}]" for prefix in ("::ffff:", "::ffff:0:", "64:ff9b::", "::"))
    return sorted(set(hosts))


@pytest.mark.skipif(shutil.which("node") is None, reason="the dashboard's copy of the rules runs on node")
def test_the_dashboard_calls_local_exactly_what_the_engine_does() -> None:
    """The consent sheet sorts a plugin's addresses with its own copy of the rules.

    Those rules are the ones Python settled on in 3.12.4, the oldest it runs on.
    """
    hosts = edges()
    script = "import('./src/urls.ts').then((urls) => console.log(JSON.stringify(JSON.parse(process.argv[1]).map(urls.isLocalAddress))))"
    answered = subprocess.run(
        ["node", "-e", script, json.dumps(hosts)], cwd=Path(__file__).resolve().parent.parent / "web", capture_output=True, text=True, check=True
    )

    dashboard = dict(zip(hosts, json.loads(answered.stdout)))
    assert dashboard == {host: urls.is_local_address(host) for host in hosts}


def test_a_pattern_reads_back_in_words() -> None:
    assert urls.phrase("https://*.spotify.com/*") == "anything on spotify.com and its subdomains"
    assert urls.phrase("https://api.spotify.com/v1/me/player") == "/v1/me/player on api.spotify.com"
    assert urls.phrase("*://*/*") == "anything on any address at all"
    assert urls.phrase("http://192.168.1.50:8080/*") == "anything on 192.168.1.50 on port 8080"
