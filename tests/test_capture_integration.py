"""
End-to-end: a real session, a real capture worker, real `mss` frames,
the real watch-region allowlist, real shared memory — proving the whole
Phase 2 pipeline works together, not just its isolated pieces.

`test_no_watch_regions_means_a_real_session_captures_nothing` is now the
central adversarial proof, stronger than the old "block everything"
version: with ZERO configuration effort, a real running session against
a real screen produces frames that are provably all-black.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from bhai.bus.bus import EventBus
from bhai.bus.events import CaptureFrameAvailable
from bhai.capture.ring import FrameRing
from bhai.capture.watch_regions import WatchRegion
from bhai.db.store import SessionStore
from bhai.session.manager import SessionManager


@pytest.mark.asyncio
async def test_a_real_session_produces_real_frame_descriptors_on_the_bus(tmp_path) -> None:
    store = SessionStore(tmp_path / "test.db")
    bus = EventBus()
    manager = SessionManager(bus, store)
    sub = bus.subscribe("capture.frame")

    try:
        manager.start()
        descriptor = await asyncio.wait_for(sub._queue.get(), timeout=5.0)

        assert isinstance(descriptor, CaptureFrameAvailable)
        assert descriptor.session_id == manager.session_id
        assert descriptor.width > 0 and descriptor.height > 0

        # Attach to the ring exactly as a real consumer (the trust
        # inspector) would, and confirm there's an actual captured frame
        # behind the descriptor — not a placeholder.
        ring = FrameRing(
            descriptor.width, descriptor.height, name=descriptor.shm_name, create=False
        )
        try:
            rgb = ring.read(descriptor.slot)
            arr = np.frombuffer(rgb, dtype=np.uint8)
            assert arr.size == descriptor.width * descriptor.height * 3
        finally:
            ring.close()
    finally:
        sub.close()
        manager.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_no_watch_regions_means_a_real_session_captures_nothing(tmp_path) -> None:
    """The adversarial test, end to end: with no RegionStore configured
    (so no watch regions resolve for any monitor), a REAL captured frame
    — not a synthetic one — comes out all-black on the other side of the
    real IPC boundary. This is the safe-by-default claim, proven against
    an actual running session."""
    store = SessionStore(tmp_path / "test.db")
    bus = EventBus()
    manager = SessionManager(bus, store)  # no region_store -> resolves to zero watch regions
    sub = bus.subscribe("capture.frame")

    try:
        manager.start()
        descriptor = await asyncio.wait_for(sub._queue.get(), timeout=5.0)

        ring = FrameRing(
            descriptor.width, descriptor.height, name=descriptor.shm_name, create=False
        )
        try:
            rgb = ring.read(descriptor.slot)
            arr = np.frombuffer(rgb, dtype=np.uint8)
            assert arr.max() == 0, "a session with no watch regions let a non-black pixel through"
        finally:
            ring.close()
    finally:
        sub.close()
        manager.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_a_full_screen_watch_region_lets_real_content_through(tmp_path) -> None:
    """Sanity check in the other direction: the allowlist actually
    allows. A real screen is overwhelmingly likely to have SOME non-zero
    pixel somewhere — if this ever flakes, it's because the whole
    physical screen was pure black at the moment of the test."""
    store = SessionStore(tmp_path / "test.db")
    bus = EventBus()
    manager = SessionManager(bus, store)
    sub = bus.subscribe("capture.frame")

    try:
        session_id = store.create_session()
        manager._session_id = session_id  # test-only: bypass start() to inject watch_regions
        manager._supervisor.spawn_capture(
            session_id, watch_regions=[WatchRegion(x=0.0, y=0.0, w=1.0, h=1.0)]
        )
        descriptor = await asyncio.wait_for(sub._queue.get(), timeout=5.0)

        ring = FrameRing(
            descriptor.width, descriptor.height, name=descriptor.shm_name, create=False
        )
        try:
            rgb = ring.read(descriptor.slot)
            arr = np.frombuffer(rgb, dtype=np.uint8)
            assert arr.max() > 0, "a full-screen watch region should let real content through"
        finally:
            ring.close()
    finally:
        sub.close()
        manager._supervisor.kill_capture(manager._session_id or "")
        manager.shutdown()
        store.close()
