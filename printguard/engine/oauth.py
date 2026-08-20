"""Signing a plugin in to a service, without the plugin ever holding the result.

PrintGuard runs the authorisation code flow with PKCE, which is what RFC 8252
asks of an app that cannot keep a client secret, and a plugin is exactly that.
The tokens land in the plugin's secrets, so it references them in a request and
PrintGuard fills them in on the way out.

The access token is refreshed when it is close to expiring rather than after a
request has already failed, and a provider that rotates its refresh tokens has
the new one kept.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from .adapters import HttpFn

logger = logging.getLogger(__name__)

ACCESS = "oauth"
REFRESH = "oauth_refresh"
EXPIRES = "oauth_expires"
"""The three secrets a sign-in writes. A plugin references the first."""

CALLBACK_PATH = "/oauth/callback"
PENDING_TTL_S = 600.0
REFRESH_MARGIN_S = 60.0


def _urlsafe(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass
class Pending:
    """One sign-in waiting for the user to come back from the provider."""

    plugin_id: str
    verifier: str
    redirect_uri: str
    started: float = field(default_factory=time.monotonic)


class OAuthFlows:
    """Runs sign-ins for plugins and keeps their tokens fresh."""

    def __init__(self, http: HttpFn) -> None:
        self._http = http
        self._pending: dict[str, Pending] = {}

    def start(self, plugin_id: str, provider: dict[str, Any], origin: str) -> str:
        """Builds the URL that sends the user to the provider.

        Args:
            plugin_id: Whose sign-in it is.
            provider: The manifest's ``oauth`` block.
            origin: Where the hub is being reached, which is where the provider
                sends the user back to.

        Returns:
            The authorize URL to open.
        """
        self._pending = {key: waiting for key, waiting in self._pending.items() if time.monotonic() - waiting.started < PENDING_TTL_S}
        verifier = _urlsafe(secrets.token_bytes(48))
        state = _urlsafe(secrets.token_bytes(24))
        redirect_uri = f"{origin.rstrip('/')}{CALLBACK_PATH}"
        self._pending[state] = Pending(plugin_id, verifier, redirect_uri)
        query = {
            "response_type": "code",
            "client_id": provider["client_id"],
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": _urlsafe(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
        }
        if provider["scopes"]:
            query["scope"] = " ".join(provider["scopes"])
        return f"{provider['authorize_url']}?{urlencode(query)}"

    def waiting_for(self, state: str) -> str | None:
        """Which plugin a returning user belongs to, or None for a stale state."""
        pending = self._pending.get(state)
        return pending.plugin_id if pending else None

    async def finish(self, state: str, code: str, provider: dict[str, Any]) -> dict[str, str]:
        """Exchanges the code the provider sent back for tokens.

        Args:
            state: What came back on the callback, which pins the request to the
                sign-in that started it.
            code: The authorisation code.
            provider: The manifest's ``oauth`` block.

        Returns:
            The secrets to store against the plugin.

        Raises:
            PermissionError: If the state is unknown or has expired, which is
                what stands in the way of a callback nobody asked for.
            RuntimeError: If the provider refused the exchange.
        """
        pending = self._pending.pop(state, None)
        if pending is None:
            raise PermissionError("no sign-in is waiting for that answer")
        return await self._tokens(provider, {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending.redirect_uri,
            "client_id": provider["client_id"],
            "code_verifier": pending.verifier,
        })

    async def refreshed(self, provider: dict[str, Any], held: dict[str, str]) -> dict[str, str] | None:
        """Renews an access token that is about to expire.

        Args:
            provider: The manifest's ``oauth`` block.
            held: The secrets currently stored for the plugin.

        Returns:
            The secrets to store, or None when the one held is still good or
            there is nothing to refresh with.
        """
        if not held.get(REFRESH) or time.time() < float(held.get(EXPIRES) or 0) - REFRESH_MARGIN_S:
            return None
        renewed = await self._tokens(provider, {
            "grant_type": "refresh_token",
            "refresh_token": held[REFRESH],
            "client_id": provider["client_id"],
        })
        return {**held, **renewed}

    async def _tokens(self, provider: dict[str, Any], form: dict[str, str]) -> dict[str, str]:
        status, body = await self._http(
            "POST",
            provider["token_url"],
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data=urlencode(form).encode(),
        )
        if status >= 400 or not isinstance(body, dict) or not body.get("access_token"):
            raise RuntimeError(f"{provider['label']} refused the sign-in ({status})")
        held = {ACCESS: str(body["access_token"]), EXPIRES: str(time.time() + float(body.get("expires_in") or 3600))}
        if body.get("refresh_token"):
            held[REFRESH] = str(body["refresh_token"])
        return held
