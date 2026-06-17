"""Scoped API tokens: the capability vocabulary and token record helpers.

Tokens gate the hub's REST and MCP transports. The engine owns them so they can
be issued, named and revoked from the same protocol the UI already speaks and
persisted alongside the rest of its state. Only a hash of each secret is kept;
the secret is shown once at creation and is unrecoverable thereafter.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from typing import Any

SCOPE_ORDER = ("read", "control", "manage")
TOKEN_PREFIX = "pg_"


def expand_scope(scope: str) -> set[str]:
    """Returns the cumulative set a granted scope implies."""
    return set(SCOPE_ORDER[: SCOPE_ORDER.index(scope) + 1])


def hash_secret(secret: str) -> str:
    """Hashes a bearer secret for storage and constant-time comparison."""
    return hashlib.sha256(secret.encode()).hexdigest()


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


def public_token(record: dict[str, Any]) -> dict[str, Any]:
    """Serialises a token record without its secret hash."""
    return {key: record[key] for key in ("id", "name", "scope", "hint", "created")}
