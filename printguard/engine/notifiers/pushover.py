"""Pushover notifier via the Messages API.

API reference: https://pushover.net/api
Creating an application token: https://pushover.net/apps/build

Each user supplies their own application token, so alerts count against
their own monthly allowance rather than a shared one.

CORS on api.pushover.net is per-endpoint. The messages endpoint sends the
headers, so this adapter runs in both modes, but users/validate.json and
sounds.json do not; calling either would break local mode alone.

Priority is configured rather than fixed, and applies to everything this
channel carries: defect alerts, watchdog warnings and recoveries, and the
settings test. NotifierAdapter.send() receives no severity, so an adapter
cannot grade a message by kind, and High bypasses the quiet hours set on
the device - which is worth having for a failed print and not for a camera
reconnecting at 03:00. Emergency (2) is deliberately absent: it requires
retry and expire parameters and an acknowledgement receipt to stop it
re-alerting, none of which PrintGuard has anywhere to put.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .base import HttpFn, NotifierAdapter, multipart_form

API = "https://api.pushover.net/1/messages.json"
PRIORITIES = ["-2", "-1", "0", "1"]
PRIORITY_LABELS = [
    "Lowest - no notification, badge only",
    "Low - notifies without a sound",
    "Normal - respects your quiet hours",
    "High - bypasses your quiet hours",
]
DEFAULT_PRIORITY = "1"


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
                "title": "Priority (applies to every notice, defaults to High)",
                "enum": PRIORITIES,
                "enum_labels": PRIORITY_LABELS,
            },
        },
        "required": ["api_token", "user_key"],
    }

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None) -> None:
        """Posts the message, as multipart with the snapshot or form-encoded without."""
        priority = str(config.get("priority", "")).strip()
        fields = {
            "token": str(config["api_token"]).strip(),
            "user": str(config["user_key"]).strip(),
            "title": title,
            "message": body,
            "priority": priority if priority in PRIORITIES else DEFAULT_PRIORITY,
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
