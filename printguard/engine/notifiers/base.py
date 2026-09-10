"""Contract for alert notifiers.

A notifier adapter delivers defect alerts through a push service via the
platform's HTTP function, so the same adapter runs in the browser (local
mode) and on the server (hub mode). Contributors add a service by
subclassing NotifierAdapter in a new module and registering an instance
in printguard.engine.notifiers.NOTIFIERS.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from ..adapters import Adapter, HttpFn, multipart_form


class NotifierAdapter(Adapter):
    """Base class for alert notifiers."""

    @abstractmethod
    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None) -> None:
        """Delivers an alert through the service.

        Args:
            http: Platform HTTP function.
            config: User-supplied values matching the adapter schema.
            title: Short alert headline.
            body: Alert detail text.
            image: JPEG snapshot of the offending frame, if available.

        Raises:
            RuntimeError: If the service rejects the notification.
        """


__all__ = ["HttpFn", "NotifierAdapter", "multipart_form"]
