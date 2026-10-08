"""Telegram notifier via the Bot API.

API reference: https://core.telegram.org/bots/api
Creating a bot with BotFather: https://core.telegram.org/bots/tutorial
"""

from __future__ import annotations

from typing import Any

from .base import HttpFn, NotifierAdapter, multipart_form, require_reply, truncated

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


class TelegramNotifier(NotifierAdapter):
    """Sends alerts from a bot to a chat, with the snapshot as a photo."""

    id = "telegram"
    label = "Telegram"
    docs_url = "https://core.telegram.org/bots/api"
    setup_url = "https://core.telegram.org/bots/tutorial"
    setup_hint = (
        "Create a bot with @BotFather to get its token, then message the bot and read your "
        "chat ID from @userinfobot."
    )
    schema = {
        "type": "object",
        "properties": {
            "bot_token": {"type": "string", "title": "Bot token", "secret": True, "placeholder": "From @BotFather"},
            "chat_id": {"type": "string", "title": "Chat ID", "placeholder": "From @userinfobot, e.g. 123456789"},
        },
        "required": ["bot_token", "chat_id"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Calls sendPhoto with a multipart upload, or sendMessage without, silently when not urgent.

        The message is cut to the 1024 characters a photo's caption takes, or the 4096 a text message does.

        Raises:
            RuntimeError: If Telegram rejects the alert, or does not answer ``ok``.
        """
        api = f"https://api.telegram.org/bot{config['bot_token']}"
        text = f"{title}\n{body}"
        if image:
            fields = {"chat_id": str(config["chat_id"]), "caption": truncated(text, CAPTION_LIMIT), **({} if urgent else {"disable_notification": "true"})}
            headers, payload = multipart_form(fields, "photo", "snapshot.jpg", image)
            status, resp = await http("POST", f"{api}/sendPhoto", headers=headers, data=payload, timeout=15.0)
        else:
            status, resp = await http("POST", f"{api}/sendMessage", json={"chat_id": config["chat_id"], "text": truncated(text, TEXT_LIMIT), **({} if urgent else {"disable_notification": True})}, timeout=15.0)
        answered = resp if isinstance(resp, dict) else {}
        require_reply("Telegram", "the alert", status, answered.get("ok") is True, answered.get("description"))
