"""Event bus: topic filtering and the drop-oldest backpressure policy."""

from __future__ import annotations

import asyncio

import pytest

from bhai.bus.bus import EventBus
from bhai.bus.events import BusEvent, CaptureWorkerStarted, SessionStateChanged
from bhai.session.states import SessionState


@pytest.mark.asyncio
async def test_topic_filtered_subscription_only_receives_matching_events() -> None:
    bus = EventBus()
    sub = bus.subscribe("capture.worker_started")
    bus.publish(SessionStateChanged(
        session_id="s1", old_state=SessionState.IDLE, new_state=SessionState.ACTIVE
    ))
    bus.publish(CaptureWorkerStarted(session_id="s1", pid=123))

    received = await asyncio.wait_for(sub._queue.get(), timeout=1.0)
    assert isinstance(received, CaptureWorkerStarted)
    assert sub._queue.empty()  # the state-changed event never arrived here


@pytest.mark.asyncio
async def test_wildcard_subscription_receives_everything() -> None:
    bus = EventBus()
    sub = bus.subscribe(None)
    bus.publish(CaptureWorkerStarted(session_id="s1", pid=1))
    bus.publish(CaptureWorkerStarted(session_id="s1", pid=2))
    first = await asyncio.wait_for(sub._queue.get(), timeout=1.0)
    second = await asyncio.wait_for(sub._queue.get(), timeout=1.0)
    assert (first.pid, second.pid) == (1, 2)


@pytest.mark.asyncio
async def test_bounded_topic_drops_oldest_under_pressure() -> None:
    bus = EventBus()
    sub = bus.subscribe("capture.frame")
    for i in range(10):  # far more than _DROP_OLDEST_MAXSIZE
        bus.publish(BusEvent(topic="capture.frame", correlation_id=str(i)))
    remaining = []
    while not sub._queue.empty():
        remaining.append(sub._queue.get_nowait().correlation_id)
    # We must have dropped the earliest ones and kept the most recent.
    assert remaining == [str(i) for i in range(10 - len(remaining), 10)]
    assert len(remaining) <= 4


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    sub = bus.subscribe("capture.worker_started")
    sub.close()
    bus.publish(CaptureWorkerStarted(session_id="s1", pid=1))
    assert sub._queue.empty()
