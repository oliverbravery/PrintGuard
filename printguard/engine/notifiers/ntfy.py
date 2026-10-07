"""ntfy notifier.

API reference: https://docs.ntfy.sh/publish/
Subscribing on a phone (how alerts are received): https://docs.ntfy.sh/subscribe/phone/

An open topic has no credential but its name, so whoever holds the topic URL
can read and publish to it, and the URL is kept as a secret: https://docs.ntfy.sh/
"""

from __future__ import annotations

import base64
from typing import Any

from .base import HttpFn, NotifierAdapter, truncated

MESSAGE_LIMIT_BYTES = 4096


def _header(text: str) -> str:
    """Encodes a header value as an RFC 2047 word unless it is printable ASCII.

    HTTP clients send header values as ASCII and refuse one with a space at
    either end, and ntfy decodes RFC 2047 in every header, so a name with an
    accent or a message with a line break or an edge space travels this way.
    """
    if text.isascii() and text.isprintable() and text == text.strip():
        return text
    return f"=?UTF-8?B?{base64.b64encode(text.encode()).decode()}?="


class NtfyNotifier(NotifierAdapter):
    """Publishes to an ntfy topic, attaching the snapshot when available."""

    id = "ntfy"
    label = "ntfy"
    docs_url = "https://docs.ntfy.sh/publish/"
    setup_url = "https://docs.ntfy.sh/subscribe/phone/"
    setup_hint = (
        "Subscribe to your topic in the ntfy app to receive alerts. Use a hard-to-guess name, "
        "anyone with it can read; protected topics need an access token."
    )
    schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "title": "Topic URL",
                "secret": True,
                "placeholder": "https://ntfy.sh/my-printers",
            },
            "token": {"type": "string", "title": "Access token (optional)", "secret": True, "placeholder": "Leave blank for open topics"},
        },
        "required": ["url"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Publishes via PUT with the snapshot as the attachment body, or as text without one.

        A self-hosted server takes attachments only once ``attachment-cache-dir``
        and ``base-url`` are set, and answers 400 until then, so an alert whose
        snapshot is refused is sent again as text. The message is cut to the
        4096 bytes ntfy takes, since it turns a longer one into an attachment.

        Raises:
            RuntimeError: If ntfy rejects the alert, or takes it only without its snapshot.
        """
        body = truncated(body, MESSAGE_LIMIT_BYTES, utf8_bytes=True)
        headers = {"Title": _header(title), **({"Priority": "urgent", "Tags": "rotating_light"} if urgent else {})}
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"
        url = str(config["url"]).strip()
        refused = None
        if image:
            attached = {**headers, "Filename": "snapshot.jpg", "Message": _header(body)}
            refused, _ = await http("PUT", url, headers=attached, data=image, timeout=15.0)
            if refused < 400:
                return
        status, _ = await http("POST", url, headers=headers, data=body.encode(), timeout=15.0)
        if status >= 400:
            raise RuntimeError(f"ntfy rejected the alert: HTTP {status}")
        if refused:
            raise RuntimeError(f"the server refused the snapshot with HTTP {refused}, so the alert was sent as text")
