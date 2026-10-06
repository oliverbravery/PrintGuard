"""Native desktop notifier.

Raises a notification through the operating system's own notification centre on
the computer running the PrintGuard desktop app - Notification Center on macOS,
a toast on Windows - via desktop-notifier, which speaks each platform's native
API (UNUserNotificationCenter, WinRT). It reaches no external service, so it
needs no configuration; because that native call exists only in the packaged
desktop app, the adapter is desktop-only and is never offered by the headless
container. The import is lazy for the same reason: the library ships only in
the desktop build.

desktop-notifier: https://github.com/samschott/desktop-notifier
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .base import HttpFn, NotifierAdapter

_SNAPSHOT_PATH = Path(tempfile.gettempdir()) / "printguard-alert.jpg"


class _LibraryWarnings(logging.Handler):
    """Collects what desktop-notifier logs as a warning, which is how it reports a notification it could not schedule."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class NativeNotifier(NotifierAdapter):
    """Posts a native OS notification, attaching the snapshot when available."""

    id = "native"
    label = "Desktop notification"
    docs_url = "https://github.com/samschott/desktop-notifier"
    desktop_only = True
    experimental = False
    setup_hint = (
        "Shows a native notification on the computer running the PrintGuard desktop app. "
        "On macOS, allow notifications for PrintGuard the first time it asks."
    )
    schema = {"type": "object", "properties": {}}

    async def send(self, http: HttpFn, config: dict[str, Any], title: str, body: str, image: bytes | None, *, urgent: bool = True) -> None:
        """Posts the alert to the OS, writing the snapshot to a file it can read."""
        await self._deliver(title, body, self._write_snapshot(image) if image else None)

    @staticmethod
    def _write_snapshot(image: bytes) -> Path:
        """Persists the snapshot where the notification can attach it as a thumbnail.

        Notification centres read the attachment by path after the send returns -
        Windows keeps a reference until the toast is drawn - so a single reused
        file is overwritten rather than deleted, bounding it to one snapshot.
        """
        _SNAPSHOT_PATH.write_bytes(image)
        return _SNAPSHOT_PATH

    async def _deliver(self, title: str, body: str, snapshot: Path | None) -> None:
        """Sends through desktop-notifier, imported lazily as it ships only in the desktop build.

        On Windows the toast's name and icon come from the AppUserModelID the library registers
        from ``app_name`` and ``app_icon``; the desktop app points ``APP_ICON`` at its bundled icon.
        macOS draws both from the signed app bundle, so it leaves ``APP_ICON`` unset and none is
        passed there.

        Raises:
            RuntimeError: If notifications are switched off for PrintGuard, or
                desktop-notifier, which logs a failure to schedule one instead
                of raising it, warned while sending.
        """
        from desktop_notifier import Attachment, DesktopNotifier, Icon

        icon = os.environ.get("APP_ICON")
        notifier = DesktopNotifier(app_name="PrintGuard", app_icon=Icon(path=Path(icon)) if icon else None)
        if not await notifier.request_authorisation():
            raise RuntimeError("notifications are switched off for PrintGuard in the system's settings")
        warnings = _LibraryWarnings()
        library = logging.getLogger("desktop_notifier")
        library.addHandler(warnings)
        try:
            await notifier.send(title=title, message=body, attachment=Attachment(path=snapshot) if snapshot else None)
        finally:
            library.removeHandler(warnings)
        if warnings.messages:
            raise RuntimeError("; ".join(warnings.messages))
