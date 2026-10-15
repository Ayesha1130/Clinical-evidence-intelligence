"""
Pure unit tests for the event bus — no DB, no network.
"""
import asyncio

import pytest

from app.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_subscriber_receives_published_event():
    bus = EventBus()
    queue = bus.subscribe("job-1")
    await bus.publish("job-1", "agent_started", {"agent": "query_analyzer"})

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.event == "agent_started"
    assert event.data == {"agent": "query_analyzer"}
    assert event.timestamp


@pytest.mark.asyncio
async def test_events_are_scoped_to_their_job_id():
    bus = EventBus()
    queue_a = bus.subscribe("job-a")
    queue_b = bus.subscribe("job-b")

    await bus.publish("job-a", "agent_started", {})

    assert queue_a.qsize() == 1
    assert queue_b.qsize() == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_to_the_same_job_both_receive_events():
    bus = EventBus()
    q1 = bus.subscribe("job-1")
    q2 = bus.subscribe("job-1")

    await bus.publish("job-1", "pipeline_started", {})

    assert q1.qsize() == 1
    assert q2.qsize() == 1


@pytest.mark.asyncio
async def test_late_subscriber_receives_history_replay():
    bus = EventBus()
    await bus.publish("job-1", "agent_started", {"agent": "query_analyzer"})
    await bus.publish("job-1", "agent_completed", {"agent": "query_analyzer"})

    queue = bus.subscribe("job-1")
    assert queue.qsize() == 2
    first = await queue.get()
    second = await queue.get()
    assert first.event == "agent_started"
    assert second.event == "agent_completed"


@pytest.mark.asyncio
async def test_unsubscribe_stops_further_delivery():
    bus = EventBus()
    queue = bus.subscribe("job-1")
    bus.unsubscribe("job-1", queue)

    await bus.publish("job-1", "agent_started", {})
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_history_is_bounded():
    bus = EventBus()
    bus._max_history = 5
    for i in range(10):
        await bus.publish("job-1", "tick", {"i": i})

    queue = bus.subscribe("job-1")
    assert queue.qsize() == 5
    first = await queue.get()
    assert first.data["i"] == 5


def test_clear_history_removes_stored_events():
    bus = EventBus()
    bus._history["job-1"] = ["something"]
    bus.clear_history("job-1")
    assert "job-1" not in bus._history
