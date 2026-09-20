"""
In-process asyncio pub/sub event bus (roadmap §2.8).

Backpressure policy is deliberate and asymmetric, per §2.8:
  - high-frequency / low-value events (frame/perception ticks) use a
    bounded queue that DROPS OLDEST — a stale frame notification is worse
    than useless, it's actively misleading.
  - everything else (state changes, errors, user-facing events) uses an
    unbounded queue — we never drop what the user said or what the
    session did.

This module has no knowledge of Qt; bhai/bus/qt_bridge.py is the only
thing that connects it to widgets.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from bhai.bus.events import BusEvent

logger = logging.getLogger(__name__)

# Topics whose queues drop the oldest item under pressure rather than block
# the publisher. Keep this list short and deliberate.
_DROP_OLDEST_TOPICS = frozenset({"capture.frame", "perception.observation"})
_DROP_OLDEST_MAXSIZE = 4


class EventBus:
    """Topic-filtered async pub/sub. One instance per process."""

    def __init__(self) -> None:
        self._subscribers: dict[str | None, list[asyncio.Queue[BusEvent]]] = defaultdict(list)

    def subscribe(self, topic: str | None = None) -> Subscription:
        """Subscribe to a specific topic, or None for every event."""
        maxsize = _DROP_OLDEST_MAXSIZE if topic in _DROP_OLDEST_TOPICS else 0
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[topic].append(queue)
        return Subscription(self, topic, queue)

    def _unsubscribe(self, topic: str | None, queue: asyncio.Queue[BusEvent]) -> None:
        subs = self._subscribers.get(topic, [])
        if queue in subs:
            subs.remove(queue)

    def publish(self, event: BusEvent) -> None:
        """Fan the event out to every matching subscriber. Never blocks."""
        targets = list(self._subscribers.get(event.topic, [])) + list(
            self._subscribers.get(None, [])
        )
        for queue in targets:
            self._put_nowait_with_backpressure_policy(queue, event)

    @staticmethod
    def _put_nowait_with_backpressure_policy(
        queue: asyncio.Queue[BusEvent], event: BusEvent
    ) -> None:
        if queue.maxsize == 0:
            # Unbounded — never drop.
            queue.put_nowait(event)
            return
        # Bounded (drop-oldest) queue: make room by discarding the oldest
        # entry if full, then enqueue the new one. Never raises QueueFull.
        while queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(event)


class Subscription:
    """Async-iterate this to receive events; `close()` when done."""

    def __init__(self, bus: EventBus, topic: str | None, queue: asyncio.Queue[BusEvent]):
        self._bus = bus
        self._topic = topic
        self._queue = queue
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[BusEvent]:
        while not self._closed:
            yield await self._queue.get()

    def close(self) -> None:
        self._closed = True
        self._bus._unsubscribe(self._topic, self._queue)
