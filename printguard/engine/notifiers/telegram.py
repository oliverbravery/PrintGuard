"""Telegram notifier via the Bot API.

API reference: https://core.telegram.org/bots/api

api.telegram.org sends no CORS headers, so this adapter is hub-only.
"""

from __future__ import annotations

from typing import Any

from .base import HttpFn, NotifierAdapter, multipart_form


class TelegramNotifier(NotifierAdapter):
    """Sends alerts from a bot to a chat, with the snapshot as a photo."""

    id = "telegram"
    label = "Telegram"
    docs_url = "https://core.telegram.org/bots/api"
    browser_ok = False
    schema = {
        "type": "object",
        "properties": {
            "bot_token": {"type": "string", "title": "Bot token", "secret": True, "placeholder": "From @BotFather"},
            "chat_id": {"type": "string", "title": "Chat ID", "placeholder": "From @userinfobot, e.g. 123456789"},
        },
        "required": ["bot_token", "chat_id"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None) -> None:
        """Calls sendPhoto with a multipart upload, or sendMessage without."""
        api = f"https://api.telegram.org/bot{config['bot_token']}"
        text = f"{title}\n{body}"
        if image:
            headers, payload = multipart_form({"chat_id": str(config["chat_id"]), "caption": text}, "photo", "snapshot.jpg", image)
            status, resp = await http("POST", f"{api}/sendPhoto", headers=headers, data=payload, timeout=15.0)
        else:
            status, resp = await http("POST", f"{api}/sendMessage", json={"chat_id": config["chat_id"], "text": text}, timeout=15.0)
        if status >= 400:
            detail = resp.get("description") if isinstance(resp, dict) else None
            raise RuntimeError(f"Telegram rejected the alert: {detail or f'HTTP {status}'}")
