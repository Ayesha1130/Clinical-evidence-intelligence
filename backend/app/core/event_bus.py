"""
In-process event bus for streaming real pipeline progress over SSE.

Deliberately not Redis/a message queue — this is a single-process
deployment (matches the project's Render/Railway single-instance target),
so an asyncio.Queue per subscriber, keyed by research_job_id, is the
correct amount of infrastructure. Every event published here corresponds
to something that actually just happened in the pipeline — never a
timer-based fake progress tick.
"""
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PipelineEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        # Replays recent events to a subscriber that connects slightly
        # late — bounded so it can't grow unbounded for a job nobody is
        # listening to.
        self._history: dict[str, list[PipelineEvent]] = defaultdict(list)
        self._max_history = 200

    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id].append(queue)
        for event in self._history.get(job_id, []):
            queue.put_nowait(event)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(job_id)
        if subscribers and queue in subscribers:
            subscribers.remove(queue)

    async def publish(self, job_id: str, event: str, data: dict | None = None) -> None:
        pipeline_event = PipelineEvent(event=event, data=data or {})

        history = self._history[job_id]
        history.append(pipeline_event)
        if len(history) > self._max_history:
            del history[: len(history) - self._max_history]

        for queue in list(self._subscribers.get(job_id, [])):
            queue.put_nowait(pipeline_event)

    def clear_history(self, job_id: str) -> None:
        self._history.pop(job_id, None)


event_bus = EventBus()
