"""Entry point Pyodide runs to start the engine inside the page."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..engine.engine import Engine
from .platform import BrowserPlatform

_engine: Engine | None = None


async def start(sink: Any) -> None:
    """Boots the engine against the JavaScript bridge.

    Args:
        sink: JavaScript callback receiving each event as a JSON string.
    """
    global _engine
    from js import window

    platform = await BrowserPlatform.create(window.__pg)
    _engine = Engine(platform)
    _engine.add_sink(lambda event: sink(json.dumps(event)))
    await _engine.start()


def handle(command_json: str) -> None:
    """Dispatches a UI command into the engine.

    Args:
        command_json: JSON-encoded protocol command.
    """
    if _engine is not None:
        asyncio.ensure_future(_engine.handle(json.loads(command_json)))
