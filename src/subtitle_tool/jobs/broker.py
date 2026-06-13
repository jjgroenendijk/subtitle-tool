"""A tiny pub/sub broker bridging the worker thread to SSE subscribers.

The worker runs in a background thread; browser subscribers live on the asyncio
event loop. The worker calls :meth:`publish` from its thread, and the broker hands
each event to every subscriber's queue on the loop via ``call_soon_threadsafe`` so
nothing crosses the thread boundary unsafely. Each connected browser
:meth:`subscribe`\\ s for the lifetime of its ``EventSource`` connection.

Events are plain JSON-serialisable dicts; the broker neither inspects nor stores
them. It is in-memory only: history lives in the SQLite store, this just pushes
live updates.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

# A queued ``None`` tells a subscriber's stream to stop (used on shutdown).
_SENTINEL: Any = None


class EventBroker:
    """Fan-out of job events from the worker thread to async subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the event loop subscribers live on; call once at app startup."""
        self._loop = loop

    def publish(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to every subscriber. Safe to call from any thread."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: dict[str, Any]) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Any]]:
        """Async context manager yielding a queue of events for one subscriber."""
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def close(self) -> None:
        """Signal every subscriber to end its stream."""
        loop = self._loop
        if loop is None:
            return
        for queue in self._subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
