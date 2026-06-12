"""ntfy notifier.

API reference: https://docs.ntfy.sh/publish/
"""

from __future__ import annotations

from typing import Any

from .base import HttpFn, NotifierAdapter


class NtfyNotifier(NotifierAdapter):
    """Publishes to an ntfy topic, attaching the snapshot when available."""

    id = "ntfy"
    label = "ntfy"
    docs_url = "https://docs.ntfy.sh/publish/"
    schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "title": "Topic URL",
                "placeholder": "https://ntfy.sh/my-printers",
            },
            "token": {"type": "string", "title": "Access token (optional)", "secret": True, "placeholder": "Leave blank for open topics"},
        },
        "required": ["url"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None) -> None:
        """Publishes via PUT with the snapshot as the attachment body."""
        headers = {"Title": title, "Priority": "urgent", "Tags": "rotating_light"}
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"
        url = str(config["url"]).strip()
        if image:
            headers["Filename"] = "snapshot.jpg"
            headers["Message"] = body
            status, _ = await http("PUT", url, headers=headers, data=image, timeout=15.0)
        else:
            status, _ = await http("POST", url, headers=headers, data=body.encode(), timeout=15.0)
        if status >= 400:
            raise RuntimeError(f"ntfy rejected the alert: HTTP {status}")
