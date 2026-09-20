"""
RegionStore: global (not session-scoped) watch-region persistence, and
the fail-closed default when no regions exist for the current monitor
signature (roadmap §2.4).
"""

from __future__ import annotations

from bhai.capture.region_store import RegionStore
from bhai.capture.watch_regions import WatchRegion
from bhai.db.store import SessionStore


def test_regions_round_trip_for_their_signature(tmp_path) -> None:
    store = RegionStore(tmp_path / "regions.db")
    try:
        sig = RegionStore.signature(1920, 1080)
        region = WatchRegion(x=0.1, y=0.1, w=0.2, h=0.2)
        store.add(sig, region)
        assert store.list_for(sig) == [region]
    finally:
        store.close()


def test_regions_are_scoped_to_their_exact_signature() -> None:
    """A region saved for one resolution must never silently apply to a
    different one — this IS the fail-closed behaviour, not a limitation
    of it."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        store = RegionStore(f"{d}/regions.db")
        try:
            store.add(RegionStore.signature(1920, 1080), WatchRegion(x=0, y=0, w=0.5, h=0.5))
            assert store.list_for(RegionStore.signature(1366, 768)) == []
        finally:
            store.close()


def test_clear_removes_only_that_signatures_regions(tmp_path) -> None:
    store = RegionStore(tmp_path / "regions.db")
    try:
        sig_a, sig_b = RegionStore.signature(1920, 1080), RegionStore.signature(1366, 768)
        store.add(sig_a, WatchRegion(x=0, y=0, w=0.1, h=0.1))
        store.add(sig_b, WatchRegion(x=0, y=0, w=0.1, h=0.1))
        store.clear(sig_a)
        assert store.list_for(sig_a) == []
        assert len(store.list_for(sig_b)) == 1
    finally:
        store.close()


def test_regions_persist_across_separate_store_instances(tmp_path) -> None:
    db_path = tmp_path / "regions.db"
    sig = RegionStore.signature(800, 600)

    writer = RegionStore(db_path)
    writer.add(sig, WatchRegion(x=0.25, y=0.25, w=0.5, h=0.5))
    writer.close()

    reader = RegionStore(db_path)
    try:
        assert len(reader.list_for(sig)) == 1
    finally:
        reader.close()


def test_regions_are_not_touched_by_discarding_a_session(tmp_path) -> None:
    """The load-bearing property: watch regions are a privacy
    CONFIGURATION, not session data, so ending/discarding a session must
    never delete them — proven against the SAME db file both stores use."""
    db_path = tmp_path / "shared.db"
    session_store = SessionStore(db_path)
    region_store = RegionStore(db_path)
    try:
        sig = RegionStore.signature(2560, 1440)
        region_store.add(sig, WatchRegion(x=0, y=0, w=0.3, h=0.3))

        session_id = session_store.create_session()
        session_store.discard_session(session_id)

        assert len(region_store.list_for(sig)) == 1
    finally:
        session_store.close()
        region_store.close()
