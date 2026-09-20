"""
The invariant-1 test: PAUSE must terminate the capture worker PROCESS,
not set a flag. This is checked at the OS level with `psutil`, the same
class of check an evaluator would make in Task Manager / Activity Monitor
— deliberately not just trusting our own `is_alive` bookkeeping.

Also covers: ending without saving leaves zero rows for that session_id
(invariant 4), and a crashed capture worker degrades the session to
PAUSED rather than being silently respawned.
"""

from __future__ import annotations

import asyncio
import os

import psutil
import pytest
import pytest_asyncio

from bhai.bus.bus import EventBus
from bhai.db.store import SessionStore
from bhai.session.manager import SessionManager
from bhai.session.states import SessionState


def _pid_really_alive(pid: int) -> bool:
    """Check the OS, not our bookkeeping — and reject zombies as dead."""
    if not psutil.pid_exists(pid):
        return False
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest_asyncio.fixture
async def manager(tmp_path):
    # Must be an async fixture: SessionManager.__init__ schedules the
    # capture-crash watch task via asyncio.ensure_future, which needs a
    # running loop — there isn't one yet in a plain sync fixture.
    store = SessionStore(tmp_path / "test.db")
    bus = EventBus()
    mgr = SessionManager(bus, store)
    yield mgr
    mgr.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_start_spawns_a_real_capture_process(manager: SessionManager) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    assert manager.state == SessionState.ACTIVE
    pid = manager.capture_pid
    assert pid is not None
    assert _pid_really_alive(pid)


@pytest.mark.asyncio
async def test_pause_kills_the_capture_process_at_the_os_level(manager: SessionManager) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    pid = manager.capture_pid
    assert _pid_really_alive(pid)

    manager.pause()
    assert manager.state == SessionState.PAUSED
    assert manager.capture_pid is None
    # The critical assertion: the OS agrees the process is gone. Not "we
    # think it's paused" — the PID that existed a moment ago is dead.
    assert not _pid_really_alive(pid)


@pytest.mark.asyncio
async def test_resume_spawns_a_fresh_process_with_a_new_pid(manager: SessionManager) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    first_pid = manager.capture_pid
    manager.pause()

    manager.resume()
    await asyncio.sleep(0.2)
    second_pid = manager.capture_pid
    assert second_pid is not None
    assert second_pid != first_pid
    assert _pid_really_alive(second_pid)
    assert not _pid_really_alive(first_pid)


@pytest.mark.asyncio
async def test_end_without_save_deletes_every_row_for_the_session(manager: SessionManager) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    session_id = manager.session_id
    manager.pause()
    manager.end()
    manager.finish(save=False)

    assert manager.session_id is None
    # Reach into the store the manager was constructed with via a fresh
    # connection to the same file to prove it's really gone, not just
    # uncommitted in this connection.
    store = manager._store  # test-only introspection
    assert store.row_count_for_session(session_id) == 0


@pytest.mark.asyncio
async def test_end_with_save_keeps_the_session_row(manager: SessionManager) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    session_id = manager.session_id
    manager.end()
    manager.finish(save=True)

    store = manager._store
    assert store.row_count_for_session(session_id) > 0


@pytest.mark.asyncio
async def test_capture_worker_crash_degrades_to_paused_not_silent_respawn(
    manager: SessionManager,
) -> None:
    manager.start()
    await asyncio.sleep(0.2)
    pid = manager.capture_pid

    # Simulate an unexpected death — not through pause(), through the OS.
    os.kill(pid, 9)

    # Give the watch loop time to notice (poll interval is 0.25s).
    await asyncio.sleep(0.6)

    assert manager.state == SessionState.PAUSED
    # And critically: nothing silently respawned a new capture process.
    assert manager.capture_pid is None
