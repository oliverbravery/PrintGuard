"""Contract for alert notifiers.

A notifier adapter delivers defect alerts through a push service via the
platform's HTTP function. Contributors add a service by subclassing
NotifierAdapter in a new module and registering an instance in
printguard.engine.notifiers.NOTIFIERS.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from ..adapters import Adapter, HttpFn, multipart_form

ELLIPSIS = "…"


def truncated(text: str, limit: int, *, utf8_bytes: bool = False) -> str:
    """Cuts text to a service's documented limit, ending in an ellipsis where it cut.

    A monitor's or a camera's name has no length cap and goes into the alert,
    so a long one would make the service refuse the alert.

    Args:
        text: What would be sent.
        limit: The most the service takes.
        utf8_bytes: Whether the limit counts UTF-8 bytes and not characters.

    Returns:
        The text, or its start and an ellipsis if it was over the limit.
    """
    if utf8_bytes:
        encoded = text.encode()
        room = limit - len(ELLIPSIS.encode())
        return text if len(encoded) <= limit else encoded[:room].decode(errors="ignore") + ELLIPSIS
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


class NotifierAdapter(Adapter):
    """Base class for alert notifiers."""

    @abstractmethod
    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Delivers an alert through the service.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.
            title: Short alert headline.
            body: Alert detail text.
            image: JPEG snapshot of the offending frame, if available.
            urgent: Whether the notice should interrupt, as a defect does. A
                notice that only informs, such as a recovery, is False, and a
                service with a quieter way to deliver one uses it.

        Raises:
            RuntimeError: If the service rejects the notification.
        """


__all__ = ["HttpFn", "NotifierAdapter", "multipart_form", "truncated"]
