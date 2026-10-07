"""Discord notifier via channel webhooks.

API reference: https://discord.com/developers/docs/resources/webhook#execute-webhook
Creating a webhook: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks
"""

from __future__ import annotations

import json
from typing import Any

from .base import HttpFn, NotifierAdapter, multipart_form, require_reply, truncated

SUPPRESS_NOTIFICATIONS = 1 << 12
CONTENT_LIMIT = 2000


class DiscordNotifier(NotifierAdapter):
    """Posts to a channel webhook, attaching the snapshot as a file."""

    id = "discord"
    label = "Discord"
    docs_url = "https://discord.com/developers/docs/resources/webhook#execute-webhook"
    setup_url = "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks"
    setup_hint = "Create a webhook under Server Settings > Integrations > Webhooks and copy its URL."
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

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Executes the webhook with payload_json and an optional file part, suppressing notifications when not urgent.

        The message is cut to the 2000 characters Discord takes, and mentions
        nobody, since a monitor or camera named ``@everyone`` would otherwise
        ping the whole channel. Discord answers 204, or the message it posted
        when the webhook URL carries ``?wait=true``.

        Raises:
            RuntimeError: If Discord rejects the alert, or the webhook URL
                answers with anything else.
        """
        url = config["webhook_url"]
        payload = {
            "content": truncated(f"**{title}**\n{body}", CONTENT_LIMIT),
            "allowed_mentions": {"parse": []},
            **({} if urgent else {"flags": SUPPRESS_NOTIFICATIONS}),
        }
        if image:
            headers, data = multipart_form({"payload_json": json.dumps(payload)}, "files[0]", "snapshot.jpg", image)
            status, reply = await http("POST", url, headers=headers, data=data, timeout=15.0)
        else:
            status, reply = await http("POST", url, json=payload, timeout=15.0)
        require_reply("Discord", "the alert", status, status == 204 or (isinstance(reply, dict) and "id" in reply))
