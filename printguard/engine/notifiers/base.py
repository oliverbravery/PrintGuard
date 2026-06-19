"""Contract for alert notifiers.

A notifier adapter delivers defect alerts through a push service via the
platform's HTTP function, so the same adapter runs in the browser (local
mode) and on the server (hub mode). Contributors add a service by
subclassing NotifierAdapter in a new module and registering an instance
in printguard.engine.notifiers.NOTIFIERS.
"""

from __future__ import annotations

import uuid
from abc import abstractmethod
from typing import Any

from ..adapters import Adapter, HttpFn


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


def multipart_form(fields: dict[str, str], file_field: str, filename: str, file_bytes: bytes) -> tuple[dict[str, str], bytes]:
    """Encodes text fields plus one JPEG as a multipart/form-data request.

    Args:
        fields: Plain form fields.
        file_field: Form name of the file part.
        filename: Filename reported for the file part.
        file_bytes: JPEG content of the file part.

    Returns:
        (headers, body) ready for the platform HTTP function.
    """
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n".encode() + file_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return {"Content-Type": f"multipart/form-data; boundary={boundary}"}, b"".join(parts)
