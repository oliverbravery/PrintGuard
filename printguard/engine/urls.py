"""URL match patterns, the scope a plugin's network grant is written in.

The grammar is the one browser extensions use, ``scheme://host/path`` with
wildcards, extended to the streaming and socket schemes PrintGuard speaks. A
bare hostname cannot say "only this endpoint", so every grant would round up to
the whole site.

A pattern naming a private or loopback address is asked for on its own. Reaching
a printer on your network is most of what a self-hosted plugin wants, and a
different thing to agree to than the internet.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import unquote, urlsplit

SCHEMES = ("http", "https", "ws", "wss", "rtsp", "rtsps")
WILDCARD_SCHEMES = ("http", "https")
"""What a ``*`` scheme covers, the same as a browser means by it."""

DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "rtsp": 554, "rtsps": 322}

PATTERN = re.compile(
    r"^(?P<scheme>\*|" + "|".join(SCHEMES) + r")://"
    r"(?P<host>\*|(?:\*\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:]+\])"
    r"(?::(?P<port>\*|\d{1,5}))?"
    r"(?P<path>/[^\s]*)$"
)

EMBEDDING_IPV4 = tuple(ipaddress.ip_network(network) for network in ("::/96", "::ffff:0:0/96", "::ffff:0:0:0/96", "64:ff9b::/96"))
"""The IPv6 ranges that carry an IPv4 address in their last 32 bits, which a network may deliver as that address."""

UNROUTED = tuple(ipaddress.ip_network(network) for network in ("224.0.0.0/4", "fec0::/10", "ff00::/8"))
"""Multicast and the retired site-local range, which the standard library calls global and no public service answers on."""

PLAIN_URL = re.compile(r"^[a-z][a-z0-9+.-]*://(?:[a-z0-9.-]+|\[[0-9a-f:]+\])(?::(?P<port>\d{1,5}))?(?:[/?#]|$)", re.IGNORECASE)

LOCAL_HOSTNAMES = ("localhost",)
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".home", ".lan", ".home.arpa")
"""Names that resolve inside a network by convention rather than by address."""


def link(raw: Any) -> str:
    """A manifest's link, kept only when it is an ordinary web address.

    Anything else, ``javascript:`` above all, is dropped here so the dashboard
    never renders it as an anchor.
    """
    url = str(raw).strip()[:200]
    parts = urlsplit(url)
    return url if parts.scheme in ("http", "https") and parts.netloc else ""


def _fold(raw: str) -> str:
    """Lowercases a pattern's scheme and host, the parts of an address that ignore case."""
    return re.sub(r"^[^/]*//[^/]*", lambda origin: origin.group().lower(), raw.strip())


def parse(raw: str) -> dict[str, str] | None:
    """Reads one pattern, or None if it is not one.

    Args:
        raw: The pattern as the manifest wrote it.

    Returns:
        Its scheme, host, port and path, or None when the pattern is malformed.
    """
    match = PATTERN.match(_fold(raw))
    if not match:
        return None
    parts = match.groupdict()
    return {**parts, "port": parts["port"] or "*"}


def _matches_host(pattern: str, host: str) -> bool:
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def _matches_path(pattern: str, path: str) -> bool:
    """Whether a path fits a pattern whose ``*`` each stand for any run of characters.

    The literal pieces are looked for in order, each as early as it can sit, so
    the work grows with the path and never with the number of wildcards.
    """
    first, *middle = pattern.split("*")
    if not middle:
        return path == first
    last = middle.pop()
    end = len(path) - len(last)
    if not path.startswith(first) or end < len(first) or not path.endswith(last):
        return False
    at = len(first)
    for piece in middle:
        found = path.find(piece, at, end)
        if found < 0:
            return False
        at = found + len(piece)
    return True


def is_plain(url: str) -> bool:
    """Whether a URL names one host to Python, an HTTP client and a browser alike.

    A backslash is a slash to a browser and part of a login to Python, so
    ``https://good.example\\@evil.example/`` is two different hosts. The same
    goes for a percent-encoded host, non-ASCII, a space or a control character
    in it.

    Args:
        url: The address as it would be requested.

    Returns:
        True when its authority is a plain host and an optional port, with no
        userinfo.
    """
    match = PLAIN_URL.match(url)
    return match is not None and int(match["port"] or 0) < 65536


def _climbs(path: str) -> bool:
    """Whether a path has a ``.`` or ``..`` segment, written out or percent-encoded.

    An HTTP client collapses those before it sends, so the path that was matched
    would not be the path that was asked for.
    """
    return any(unquote(segment) in (".", "..") for segment in path.replace("\\", "/").split("/"))


def matches(pattern: str, url: str) -> bool:
    """Whether a URL falls inside one pattern.

    Args:
        pattern: The pattern as the manifest wrote it.
        url: The URL a plugin asked for.

    Returns:
        True when scheme, host, port and path all match. The path is matched
        on its own, so a ``*`` in it is never satisfied by the query string. A
        pattern with a ``?`` matches what follows it against the query, and one
        without covers any query. A path with a ``.`` or ``..`` segment matches
        nothing.
    """
    rule = parse(pattern)
    if rule is None:
        return False
    if not is_plain(url):
        return False
    parsed = urlsplit(url)
    scheme, host = parsed.scheme.lower(), (parsed.hostname or "").lower()
    if not host or scheme not in (WILDCARD_SCHEMES if rule["scheme"] == "*" else (rule["scheme"],)):
        return False
    if rule["port"] != "*" and int(rule["port"]) != (parsed.port or DEFAULT_PORTS.get(scheme, 0)):
        return False
    path = parsed.path or "/"
    if _climbs(path):
        return False
    path_rule, scoped, query_rule = rule["path"].partition("?")
    if not _matches_host(rule["host"].strip("[]"), host) or not _matches_path(path_rule, path):
        return False
    return not scoped or _matches_path(query_rule, parsed.query)


def allowed(url: str, patterns: list[str]) -> bool:
    """Whether any of a plugin's patterns covers a URL."""
    return any(matches(pattern, url) for pattern in patterns)


def is_local_address(host: str) -> bool:
    """Whether a host literal is an address on the machine or its network.

    An IPv4 address is read in every spelling a resolver takes, so ``127.1``,
    ``0x7f.0.0.1`` and ``2130706433`` are all the loopback address. An IPv4
    address written inside an IPv6 one is judged as the IPv4 address it is,
    which Python only began doing for itself part way through 3.12. Multicast
    and site-local addresses count as local, though the standard library calls
    them global.
    """
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return host in LOCAL_HOSTNAMES or host.endswith(LOCAL_SUFFIXES)
    if address.version == 6 and any(address in network for network in EMBEDDING_IPV4):
        address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return not address.is_global or address.is_private or address.is_loopback or any(address in network for network in UNROUTED)


def reaches_local(pattern: str) -> bool:
    """Whether a pattern can land on the machine's own network.

    A wildcard host counts, since it covers private addresses too, which makes
    ``*://*/*`` the widest thing a plugin can ask for.
    """
    rule = parse(pattern)
    return rule is not None and (rule["host"] == "*" or is_local_address(rule["host"].replace("*.", "any.", 1)))


def is_local_url(url: str) -> bool:
    """Whether a URL's host is written as an address or a name that is on this network.

    A name that merely resolves to one is for the connection to catch, since the
    answer can change between a lookup here and the one that connects.
    """
    host = (urlsplit(url).hostname or "").lower()
    return not host or is_local_address(host)


def phrase(pattern: str) -> str:
    """Says in words what a pattern covers, for the dialog that asks about it.

    Args:
        pattern: The pattern as the manifest wrote it.

    Returns:
        A phrase naming the reach, such as "anything on printguard.io and its
        subdomains", or the pattern itself if it cannot be read.
    """
    rule = parse(pattern)
    if rule is None:
        return pattern
    where = (
        "any address at all"
        if rule["host"] == "*"
        else f"{rule['host'][2:]} and its subdomains"
        if rule["host"].startswith("*.")
        else rule["host"]
    )
    port = "" if rule["port"] == "*" else f" on port {rule['port']}"
    what = "anything on" if rule["path"] == "/*" else f"{rule['path'].rstrip('*')} on"
    return f"{what} {where}{port}"


def sanitise(raw: Any) -> list[str]:
    """Validates the patterns a manifest declared.

    Args:
        raw: The manifest's ``urls`` field.

    Returns:
        The patterns, deduplicated, with scheme and host lowercased.

    Raises:
        ValueError: If any of them is not a match pattern.
    """
    patterns = sorted({_fold(str(item)) for item in raw or [] if str(item).strip()})
    unreadable = [pattern for pattern in patterns if parse(pattern) is None]
    if unreadable:
        raise ValueError(f"not a URL match pattern: {', '.join(unreadable)}")
    return patterns
