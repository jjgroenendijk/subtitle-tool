"""The Server-Sent Events stream of live job progress.

Kept as a standalone async generator (rather than a closure in the app factory) so
it can be unit-tested directly by driving the broker: test transports buffer a
whole response and cannot consume an unbounded stream, but the generator's
behaviour is exactly what matters.

The wire format is the SSE convention: an ``event:`` line naming the event type and
a ``data:`` line with the JSON payload, separated by a blank line. A periodic
comment keeps idle connections (and any intervening proxy) alive.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from subtitle_tool.jobs import EventBroker

HEARTBEAT_SECONDS = 15.0


def format_event(event: dict[str, Any]) -> str:
    """Render one event dict as an SSE message."""
    return f"event: {event['event']}\ndata: {json.dumps(event)}\n\n"


async def event_stream(
    broker: EventBroker, *, heartbeat: float = HEARTBEAT_SECONDS
) -> AsyncIterator[str]:
    """Yield SSE messages for every published event until the broker closes."""
    async with broker.subscribe() as queue:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if event is None:  # sentinel from broker.close()
                break
            yield format_event(event)
