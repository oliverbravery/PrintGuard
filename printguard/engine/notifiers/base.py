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


__all__ = ["HttpFn", "NotifierAdapter", "multipart_form"]
