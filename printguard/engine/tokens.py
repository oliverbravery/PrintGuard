"""Scoped API tokens, the capability vocabulary and token record helpers.

Tokens gate the hub's REST and MCP transports. The engine owns them so they can
be issued, named and revoked from the same protocol the UI already speaks and
persisted alongside the rest of its state. Only a hash of each secret is kept;
the secret is shown once at creation and is unrecoverable thereafter.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
import time
import uuid
from typing import Any

from .bounds import clamp

SCOPE_ORDER = ("read", "control", "manage")
TOKEN_PREFIX = "pg_"


def expand_scope(scope: str) -> set[str]:
    """Returns the cumulative set a granted scope implies."""
    return set(SCOPE_ORDER[: SCOPE_ORDER.index(scope) + 1])


def hash_secret(secret: str) -> str:
    """Hashes a bearer secret for storage and constant-time comparison."""
    return hashlib.sha256(secret.encode()).hexdigest()


def stored_token(record: dict[str, Any]) -> dict[str, Any]:
    """Reads a token back from the state store, leaving out a field a later version retired.

    Args:
        record: One token as ``Token.persisted`` wrote it.

    Returns:
        The fields a ``Token`` is built from.

    Raises:
        KeyError: If the record is missing one of them.
        ValueError: If a value is not of the kind its field takes.
    """
    token = {key: record[key] for key in ("id", "name", "scope", "hash", "hint", "created")}
    if token["scope"] not in SCOPE_ORDER:
        raise ValueError(f"it has an unknown scope {token['scope']!r}")
    if not all(isinstance(token[key], str) for key in ("name", "hash", "hint")):
        raise ValueError("its name, hash and hint are text")
    clamp("created", token["created"], 0.0, sys.float_info.max)
    return token


def new_token(name: str, scope: str) -> tuple[dict[str, Any], str]:
    """Mints a token record and its one-time secret.

    The record keeps only the hash and a short display hint; the returned secret
    is the sole copy and is never persisted.
    """
    if scope not in SCOPE_ORDER:
        raise ValueError(f"unknown scope {scope!r}")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "scope": scope,
        "hash": hash_secret(secret),
        "hint": secret[:10] + "…",
        "created": time.time(),
    }
    return record, secret
