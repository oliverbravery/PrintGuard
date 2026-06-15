"""Alert notifier registry.

To add a service: create a module in this package with a NotifierAdapter
subclass and register an instance below. The settings form, test button
and alert delivery follow from the adapter alone — no other code changes
are required in either mode.
"""

from __future__ import annotations

from typing import Any

from .base import NotifierAdapter
from .discord import DiscordNotifier
from .ntfy import NtfyNotifier
from .telegram import TelegramNotifier

NOTIFIERS: dict[str, NotifierAdapter] = {
    adapter.id: adapter for adapter in (NtfyNotifier(), TelegramNotifier(), DiscordNotifier())
}


def notifiers_meta() -> list[dict[str, Any]]:
    """Serialises every adapter's metadata for configuration UIs."""
    return [adapter.meta() for adapter in NOTIFIERS.values()]


__all__ = ["NotifierAdapter", "NOTIFIERS", "notifiers_meta"]
