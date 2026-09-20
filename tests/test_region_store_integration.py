"""
End-to-end: a region saved through RegionStore — the same path the
watch-area editor UI actually uses — reaches a real capture worker with
no manual `watch_regions=` wiring at the call site. This is what proves
SessionManager's `_resolve_watch_regions` does its job rather than just
existing.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from bhai.bus.bus import EventBus
from bhai.capture.region_store import RegionStore
from bhai.capture.ring import FrameRing
from bhai.capture.watch_regions import WatchRegion
from bhai.db.store import SessionStore
from bhai.platform.portable.capture_mss import get_monitor_signature
from bhai.session.manager import SessionManager


@pytest.mark.asyncio
async def test_a_watch_region_saved_via_region_store_lets_real_content_through(tmp_path) -> None:
    store = SessionStore(tmp_path / "session.db")
    region_store = RegionStore(tmp_path / "session.db")  # same file, WAL-shared
    bus = EventBus()

    # Allow the whole primary monitor — same effect as the "full screen"
    # sanity test in test_capture_integration.py, but reached purely
    # through the store a real watch-area editor would write to, with
    # SessionManager doing the lookup itself.
    signature = get_monitor_signature("1")
    region_store.add(signature, WatchRegion(x=0.0, y=0.0, w=1.0, h=1.0))

    manager = SessionManager(bus, store, region_store=region_store)
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
            assert arr.max() > 0, (
                "a full-screen region saved via RegionStore did not let content through"
            )
        finally:
            ring.close()
    finally:
        sub.close()
        manager.shutdown()
        store.close()
        region_store.close()


@pytest.mark.asyncio
async def test_no_region_saved_for_this_resolution_means_black(tmp_path) -> None:
    """The other half of the proof: a RegionStore exists and even has
    rows in it, but none for THIS monitor's resolution — so the safe
    default (black) still applies rather than falling back to "allow
    everything" because a store happened to be configured."""
    store = SessionStore(tmp_path / "session.db")
    region_store = RegionStore(tmp_path / "session.db")
    bus = EventBus()

    # A region for a resolution this machine's monitor almost certainly
    # isn't running at — proves signature scoping, not just presence.
    region_store.add(RegionStore.signature(1, 1), WatchRegion(x=0.0, y=0.0, w=1.0, h=1.0))

    manager = SessionManager(bus, store, region_store=region_store)
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
            assert arr.max() == 0, "a region for a different resolution should never apply here"
        finally:
            ring.close()
    finally:
        sub.close()
        manager.shutdown()
        store.close()
        region_store.close()
