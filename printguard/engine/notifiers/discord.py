"""Discord notifier via channel webhooks.

API reference: https://discord.com/developers/docs/resources/webhook#execute-webhook
"""

from __future__ import annotations

import json
from typing import Any

from .base import HttpFn, NotifierAdapter, multipart_form


class DiscordNotifier(NotifierAdapter):
    """Posts to a channel webhook, attaching the snapshot as a file."""

    id = "discord"
    label = "Discord"
    docs_url = "https://discord.com/developers/docs/resources/webhook#execute-webhook"
    schema = {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "format": "uri",
                "title": "Webhook URL",
                "secret": True,
                "placeholder": "https://discord.com/api/webhooks/…",
            },
        },
        "required": ["webhook_url"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None) -> None:
        """Executes the webhook with payload_json and an optional file part."""
        url = str(config["webhook_url"]).strip()
        payload = {"content": f"**{title}**\n{body}"}
        if image:
            headers, data = multipart_form({"payload_json": json.dumps(payload)}, "files[0]", "snapshot.jpg", image)
            status, _ = await http("POST", url, headers=headers, data=data, timeout=15.0)
        else:
            status, _ = await http("POST", url, json=payload, timeout=15.0)
        if status >= 400:
            raise RuntimeError(f"Discord rejected the alert: HTTP {status}")
