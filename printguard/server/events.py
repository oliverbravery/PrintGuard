"""Backpressure-aware buffering for engine transport events."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any


class ConflatedEventQueue:
    """Keeps ordered events intact while replacing stale telemetry."""

    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque()
        self._state: dict[str, Any] | None = None
        self._results: dict[str, dict[str, Any]] = {}
        self._ready = asyncio.Event()

    def put(self, event: dict[str, Any]) -> None:
        """Queues an event, conflating replaceable state and result updates."""
        kind = event.get("event")
        if kind == "result":
            self._results[event["monitor_id"]] = event
        elif kind == "state" and event.get("req_id") is None:
            self._state = event
        else:
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
