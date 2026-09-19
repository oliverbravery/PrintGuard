"""One logging setup for every runtime, with an in-memory tail for bug reports.

Modules log through the stdlib as usual; entry points call ``setup`` (or
``setup_from_env`` where the environment configures deployment) exactly once.
Every record then reaches stdout for ``docker logs``, a rotating file where no
console exists (the desktop app), and a bounded in-memory tail that bug
reports attach.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from collections import deque
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
TAIL_LINES = 400
FILE_MAX_BYTES = 2_000_000
FILE_BACKUPS = 2


class TailHandler(logging.Handler):
    """Keeps the newest formatted log lines in memory."""

    def __init__(self, capacity: int = TAIL_LINES) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        """Formats and retains one record."""
        self.lines.append(self.format(record))


tail = TailHandler()


def recent() -> list[str]:
    """The retained log tail, oldest line first."""
    return list(tail.lines)


def setup(level: str = "INFO", file: Path | None = None) -> None:
    """Configures the root logger for this process.

    Args:
        level: Root level name (DEBUG, INFO, WARNING, ERROR).
        file: Rotating log file for deployments without a console, or None.

    Installs the in-memory tail, a stdout stream (absent in windowed
    PyInstaller builds, where stdout is None) and the optional file handler,
    replacing whatever was configured before so uvicorn's loggers propagate
    here too. httpx is capped at WARNING: its per-request INFO lines flood
    the tail, and they print full request URLs - which for Telegram embed
    the bot token in the path - onto unscrubbed console logs.
    """
    formatter = logging.Formatter(FORMAT)
    handlers: list[logging.Handler] = [tail]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    if file is not None:
        handlers.append(logging.handlers.RotatingFileHandler(file, maxBytes=FILE_MAX_BYTES, backupCount=FILE_BACKUPS))
    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def setup_from_env() -> None:
    """Configures logging from LOG_LEVEL and LOG_FILE."""
    file = os.environ.get("LOG_FILE")
    setup(os.environ.get("LOG_LEVEL", "INFO"), Path(file) if file else None)
