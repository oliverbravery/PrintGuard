"""URL match patterns, the scope a plugin's network grant is written in.

The grammar is the one Chrome and Firefox extensions use, ``scheme://host/path``
with wildcards, extended past http and https to the streaming and socket schemes
PrintGuard speaks. A bare hostname would have been simpler, but it cannot say
"only this endpoint", so every grant would round up to the whole site.

Patterns naming a private or loopback address are separated out rather than
refused: reaching a printer or a hub on the same network is most of what a
self-hosted plugin wants, but it is a different thing to agree to than reaching
the internet, so it is asked for on its own.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlsplit

SCHEMES = ("http", "https", "ws", "wss", "rtsp", "rtsps")
WILDCARD_SCHEMES = ("http", "https")
"""What a ``*`` scheme covers, which is what a browser means by it too."""

DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "rtsp": 554, "rtsps": 322}

PATTERN = re.compile(
    r"^(?P<scheme>\*|" + "|".join(SCHEMES) + r")://"
    r"(?P<host>\*|(?:\*\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:]+\])"
    r"(?::(?P<port>\*|\d{1,5}))?"
    r"(?P<path>/[^\s]*)$"
)

LOCAL_HOSTNAMES = ("localhost",)
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".home", ".lan")
"""Names that resolve inside a network by convention rather than by address."""


def parse(raw: str) -> dict[str, str] | None:
    """Reads one pattern, or None if it is not one.

    Args:
        raw: The pattern as the manifest wrote it.

    Returns:
        Its scheme, host, port and path, or None when the pattern is malformed.
    """
    match = PATTERN.match(raw.strip().lower())
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
    return re.fullmatch(".*?".join(re.escape(part) for part in pattern.split("*")), path) is not None


def matches(pattern: str, url: str) -> bool:
    """Whether a URL falls inside one pattern.

    Args:
        pattern: The pattern as the manifest wrote it.
        url: The URL a plugin asked for.

    Returns:
        True when scheme, host, port and path all match. The query string is
        matched as part of the path, which is what a browser does, so a pattern
        ending in ``*`` covers a URL's parameters too.
    """
    rule = parse(pattern)
    if rule is None:
        return False
    parsed = urlsplit(url.strip())
    scheme, host = parsed.scheme.lower(), (parsed.hostname or "").lower()
    if not host or scheme not in (WILDCARD_SCHEMES if rule["scheme"] == "*" else (rule["scheme"],)):
        return False
    if rule["port"] != "*" and int(rule["port"]) != (parsed.port or DEFAULT_PORTS.get(scheme, 0)):
        return False
    path = parsed.path or "/"
    return _matches_host(rule["host"], host) and _matches_path(rule["path"], f"{path}?{parsed.query}" if parsed.query else path)


def allowed(url: str, patterns: list[str]) -> bool:
    """Whether any of a plugin's patterns covers a URL."""
    return any(matches(pattern, url) for pattern in patterns)


def is_local_address(host: str) -> bool:
    """Whether a host literal is an address on the machine or its network."""
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host in LOCAL_HOSTNAMES or host.endswith(LOCAL_SUFFIXES)
    return not address.is_global or address.is_private or address.is_loopback


def reaches_local(pattern: str) -> bool:
    """Whether a pattern can land on the machine's own network.

    A wildcard host counts, since it covers every private address as readily as
    a public one, which is what makes ``*://*/*`` the widest thing a plugin can
    ask for.
    """
    rule = parse(pattern)
    return rule is not None and (rule["host"] == "*" or is_local_address(rule["host"].removeprefix("*.")))


def resolves_local(url: str) -> bool:
    """Whether a URL's host resolves to an address on this network.

    The literal is checked first so an address needs no lookup at all, then the
    name is resolved and every answer is checked, since a public name is free to
    point at a private address. A name that will not resolve is not local, since
    it is not anywhere and the request is about to fail on its own.

    Between this check and the connection the name could be re-resolved to
    somewhere else, which no allowlist closes on its own, so this decides which
    permission a request needs rather than standing as the only thing in its way.
    """
    host = (urlsplit(url.strip()).hostname or "").lower()
    if not host:
        return True
    if is_local_address(host):
        return True
    try:
        answers = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return any(is_local_address(answer[4][0]) for answer in answers)


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
        The patterns, lowercased and deduplicated.

    Raises:
        ValueError: If any of them is not a match pattern.
    """
    patterns = sorted({str(item).strip().lower() for item in raw or [] if str(item).strip()})
    unreadable = [pattern for pattern in patterns if parse(pattern) is None]
    if unreadable:
        raise ValueError(f"not a URL match pattern: {', '.join(unreadable)}")
    return patterns
