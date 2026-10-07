"""Pushover notifier via the Messages API.

API reference: https://pushover.net/api
Creating an application token: https://pushover.net/apps/build

Emergency (2) is absent from the priorities. It needs retry and expire
parameters and an acknowledgement receipt to stop it re-alerting, and
PrintGuard has nowhere to hold one.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .base import HttpFn, NotifierAdapter, multipart_form, truncated

API = "https://api.pushover.net/1/messages.json"
PRIORITIES = ["-2", "-1", "0", "1"]
PRIORITY_LABELS = [
    "Lowest - no notification, badge only",
    "Low - notifies without a sound",
    "Normal - respects your quiet hours",
    "High - bypasses your quiet hours",
]
DEFAULT_PRIORITY = "1"
TITLE_LIMIT = 250
MESSAGE_LIMIT = 1024


class PushoverNotifier(NotifierAdapter):
    """Sends alerts to a Pushover user or group, with the snapshot attached."""

    id = "pushover"
    label = "Pushover"
    docs_url = "https://pushover.net/api"
    setup_url = "https://pushover.net/apps/build"
    setup_hint = (
        "Create an application at pushover.net/apps/build for its API token. Your user key is "
        "on the Pushover dashboard, and the app is a one-off purchase per platform."
    )
    schema = {
        "type": "object",
        "properties": {
            "api_token": {
                "type": "string",
                "title": "Application API token",
                "secret": True,
                "placeholder": "From pushover.net/apps/build",
            },
            "user_key": {
                "type": "string",
                "title": "User key",
                "secret": True,
                "placeholder": "From your Pushover dashboard",
            },
            "priority": {
                "type": "string",
                "title": "Priority (applies to every notice)",
                "enum": PRIORITIES,
                "enum_labels": PRIORITY_LABELS,
                "default": DEFAULT_PRIORITY,
            },
        },
        "required": ["api_token", "user_key"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Posts the message, as multipart with the snapshot or form-encoded without.

        A notice that is not urgent goes at normal priority, or lower where the
        configured priority is lower. The title is cut to the 250 characters
        Pushover takes and the message to 1024.
        """
        priority = str(config.get("priority", ""))
        priority = priority if priority in PRIORITIES else DEFAULT_PRIORITY
        if not urgent:
            priority = str(min(int(priority), 0))
        fields = {
            "token": config["api_token"],
            "user": config["user_key"],
            "title": truncated(title, TITLE_LIMIT),
            "message": truncated(body, MESSAGE_LIMIT),
            "priority": priority,
        }
        if image:
            headers, payload = multipart_form(fields, "attachment", "snapshot.jpg", image)
        else:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            payload = urlencode(fields).encode()
        status, resp = await http("POST", API, headers=headers, data=payload, timeout=15.0)
        if status >= 400:
            errors = resp.get("errors") if isinstance(resp, dict) else None
            detail = "; ".join(errors) if isinstance(errors, list) else None
            raise RuntimeError(f"Pushover rejected the alert: {detail or f'HTTP {status}'}")
