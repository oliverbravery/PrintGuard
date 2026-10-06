"""Backpressure-aware buffering and strict JSON coding for engine transport events."""

from __future__ import annotations

import asyncio
import json
import math
from collections import deque
from typing import Any


def parse_json(text: str) -> Any:
    """Reads JSON the way a browser would, refusing every number that is not finite.

    Python reads NaN, Infinity and a literal such as 1e999 as floats, none of
    which a browser's parser or ``encode_event`` takes back.

    Args:
        text: The JSON document.

    Raises:
        ValueError: If it is not JSON or holds a non-finite number.
    """
    return require_finite(json.loads(text))


def require_finite(value: Any) -> Any:
    """Checks that no number inside a parsed body is NaN or infinite.

    Args:
        value: Parsed JSON of any shape.

    Returns:
        The same value.

    Raises:
        ValueError: If a number anywhere inside it is not finite.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("send a finite number, not NaN or Infinity")
    if isinstance(value, dict):
        for item in value.values():
            require_finite(item)
    elif isinstance(value, list):
        for item in value:
            require_finite(item)
    return value


def encode_event(event: dict[str, Any]) -> str:
    """Writes an event as the JSON a dashboard can parse.

    Args:
        event: The event to send.

    Raises:
        ValueError: If it holds NaN or Infinity, which a browser's parser rejects.
    """
    return json.dumps(event, allow_nan=False)


class ConflatedEventQueue:
    """Keeps ordered events intact while replacing stale telemetry."""

    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque()
        self._state: dict[str, Any] | None = None
        self._results: dict[str, dict[str, Any]] = {}
        self._ready = asyncio.Event()

    def put(self, event: dict[str, Any]) -> None:
        """Queues an event, conflating replaceable state and result updates.

        A command's state is newer than a tick's state still waiting, so it
        drops that one, which would otherwise be delivered after it and undo
        the command on screen until the next tick.
        """
        kind = event.get("event")
        if kind == "result":
            self._results[event["monitor_id"]] = event
        elif kind == "state" and event.get("req_id") is None:
            self._state = event
        else:
            if kind == "state":
                self._state = None
            self._events.append(event)
        self._ready.set()

    async def get(self) -> dict[str, Any]:
        """Returns the next ordered event or newest replaceable update."""
        while not self._events and self._state is None and not self._results:
            self._ready.clear()
            await self._ready.wait()
        if self._events:
            return self._events.popleft()
        if self._state is not None:
            state, self._state = self._state, None
            return state
        monitor_id = next(iter(self._results))
        return self._results.pop(monitor_id)
