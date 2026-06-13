"""Tests for the Server-Sent Events stream generator.

Driven directly against the broker: test transports buffer whole responses and
cannot consume an unbounded stream, so the generator is exercised here rather than
over HTTP.
"""

from __future__ import annotations

import asyncio

from subtitle_tool.jobs import EventBroker
from subtitle_tool.web.sse import event_stream, format_event


def test_format_event_uses_sse_wire_format() -> None:
    message = format_event({"event": "job_finished", "job_id": 3, "status": "succeeded"})

    assert message.startswith("event: job_finished\n")
    assert '"status": "succeeded"' in message
    assert message.endswith("\n\n")


def test_stream_yields_published_events_then_stops_on_close() -> None:
    async def scenario() -> list[str]:
        broker = EventBroker()
        broker.bind_loop(asyncio.get_running_loop())
        collected: list[str] = []

        async def consume() -> None:
            async for chunk in event_stream(broker, heartbeat=60):
                collected.append(chunk)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)  # let the subscriber register
        broker.publish({"event": "job_started", "job_id": 1, "mode": "real"})
        broker.publish({"event": "job_finished", "job_id": 1, "status": "succeeded"})
        await asyncio.sleep(0.05)
        broker.close()  # ends the stream
        await asyncio.wait_for(task, timeout=2.0)
        return collected

    chunks = asyncio.run(scenario())

    assert chunks[0] == ": connected\n\n"
    assert any("event: job_started" in chunk for chunk in chunks)
    assert any("event: job_finished" in chunk for chunk in chunks)


def test_stream_emits_keepalive_when_idle() -> None:
    async def scenario() -> list[str]:
        broker = EventBroker()
        broker.bind_loop(asyncio.get_running_loop())
        collected: list[str] = []

        async def consume() -> None:
            async for chunk in event_stream(broker, heartbeat=0.01):
                collected.append(chunk)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)  # long enough for at least one heartbeat
        broker.close()
        await asyncio.wait_for(task, timeout=2.0)
        return collected

    chunks = asyncio.run(scenario())

    assert any("keepalive" in chunk for chunk in chunks)
