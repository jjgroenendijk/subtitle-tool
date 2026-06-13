"""Tests for the event broker that fans job events out to SSE subscribers."""

from __future__ import annotations

import asyncio

from subtitle_tool.jobs import EventBroker


def test_publish_reaches_every_subscriber() -> None:
    async def scenario() -> tuple[dict, dict]:
        broker = EventBroker()
        broker.bind_loop(asyncio.get_running_loop())
        async with broker.subscribe() as first, broker.subscribe() as second:
            # publish() is the thread-safe entry point; here it runs on the loop.
            broker.publish({"event": "ping"})
            # Let the call_soon_threadsafe callback run.
            await asyncio.sleep(0)
            return await first.get(), await second.get()

    a, b = asyncio.run(scenario())
    assert a == {"event": "ping"} == b


def test_unsubscribed_queue_stops_receiving() -> None:
    async def scenario() -> int:
        broker = EventBroker()
        broker.bind_loop(asyncio.get_running_loop())
        async with broker.subscribe() as queue:
            pass
        broker.publish({"event": "after"})
        await asyncio.sleep(0)
        return queue.qsize()

    assert asyncio.run(scenario()) == 0


def test_publish_without_a_loop_is_a_noop() -> None:
    # Before startup binds a loop, publishing must not raise.
    EventBroker().publish({"event": "ignored"})
