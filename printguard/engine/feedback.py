"""Sends reviewed frames to the training inbox, a Cloudflare Worker.

The Worker issues each hub a token on first use and holds every limit, so this
module only registers, uploads and reports what the Worker said. Frames leave
the hub only when a person has reviewed a print and pressed Send.
"""

from __future__ import annotations

import json
from typing import Any

from .adapters import HttpFn

ENDPOINT = "https://printguard-feedback.oliverbravery.uk"
FRAME_BYTES_MAX = 150 * 1024
TIMEOUT_S = 20.0


class Refused(Exception):
    """The inbox did not take a frame.

    Attributes:
        code: Why, as the Worker names it, or ``offline`` when it could not be reached.
        retry_at: Wall-clock time the limit resets, when the Worker gave one.
    """

    def __init__(self, code: str, retry_at: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_at = retry_at


async def _call(http: HttpFn, method: str, path: str, **request: Any) -> Any:
    try:
        status, body = await http(method, f"{ENDPOINT}{path}", timeout=TIMEOUT_S, **request)
    except Exception as exc:
        raise Refused("offline") from exc
    if status >= 300:
        answer = body if isinstance(body, dict) else {}
        raise Refused(str(answer.get("code") or "offline"), answer.get("retry_at"))
    return body


async def register(http: HttpFn) -> str:
    """Asks the inbox for this hub's token.

    Raises:
        Refused: If the network has registered too many hubs today, or the inbox is unreachable.
    """
    return str((await _call(http, "POST", "/register", json={}))["token"])


async def put_frame(http: HttpFn, token: str, jpeg: bytes, details: dict[str, Any]) -> None:
    """Uploads one labelled frame.

    Args:
        http: Platform HTTP function.
        token: The hub's token from ``register``.
        jpeg: The frame, no larger than ``FRAME_BYTES_MAX``.
        details: The frame's print and frame ids, label, kind, score and context.

    Raises:
        Refused: If a limit was hit, the token was not recognised or the inbox is unreachable.
    """
    await _call(
        http,
        "PUT",
        "/frame",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg", "X-Frame": json.dumps(details)},
        data=jpeg,
    )
