"""
WorkerSupervisor — spawns, kills, and watches the capture worker; drains
its frame-descriptor queue onto the event bus.

This is the piece that turns invariant 1 ("the capture handle lives in a
worker process whose lifetime IS the session state") from a sentence in a
planning doc into something a test can assert on: `capture_alive` reflects
a real PID that a test can probe with `os.kill(pid, 0)`, and that Activity
Monitor / Task Manager can show disappearing the instant PAUSE is pressed.

SessionManager is the only caller. Nothing else in this codebase may spawn
or kill a capture worker — enforced here by convention and by
tests/test_platform_isolation.py's grep-based check, not by a language
boundary (PROJECT_CONTEXT §8 invariant 1).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import queue as queue_module
from collections.abc import Callable

import structlog

from bhai.bus.bus import EventBus
from bhai.bus.events import CaptureFrameAvailable, CaptureWorkerStarted, CaptureWorkerStopped
from bhai.capture.watch_regions import WatchRegion
from bhai.workers import capture_worker
from bhai.workers.base import WorkerHandle, spawn

logger = structlog.get_logger(__name__)

# Liveness poll interval. is_alive() is a cheap waitpid/poll, not a syscall
# storm, so this can be tight without costing meaningful CPU.
_WATCH_INTERVAL_S = 0.25

# How often to drain the frame-descriptor queue onto the bus. Descriptors
# are tiny (a shm name + a few ints) — polling this fast costs nothing,
# and it keeps the trust inspector feeling live.
_FRAME_DRAIN_INTERVAL_S = 0.05

# Bounded so a consumer that stops draining can't grow this without limit;
# the capture worker already never blocks on a full queue (put_nowait).
_FRAME_QUEUE_MAXSIZE = 4


class WorkerSupervisor:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._capture: WorkerHandle | None = None
        self._frame_queue: multiprocessing.Queue | None = None
        self._watch_task: asyncio.Task | None = None
        self._drain_task: asyncio.Task | None = None

    @property
    def capture_alive(self) -> bool:
        return self._capture is not None and self._capture.is_alive

    @property
    def capture_pid(self) -> int | None:
        return self._capture.pid if self._capture else None

    def spawn_capture(
        self,
        session_id: str,
        monitor_id: str = "1",
        watch_regions: list[WatchRegion] | None = None,
    ) -> WorkerHandle:
        if self.capture_alive:
            raise RuntimeError(
                "capture worker already running — refusing to spawn a second one; "
                "there must only ever be one capture process at a time"
            )
        frame_queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=_FRAME_QUEUE_MAXSIZE)
        handle = spawn(capture_worker.run, args=(frame_queue, monitor_id, watch_regions or []))
        self._capture = handle
        self._frame_queue = frame_queue
        self._start_frame_drain(session_id)
        logger.info("capture_worker_started", pid=handle.pid, session_id=session_id)
        self._bus.publish(CaptureWorkerStarted(session_id=session_id, pid=handle.pid))
        return handle

    def kill_capture(self, session_id: str) -> None:
        if self._capture is None:
            return
        pid = self._capture.pid
        self._capture.terminate()
        self._capture = None
        self._stop_frame_drain()
        self._frame_queue = None
        logger.info("capture_worker_stopped", pid=pid, session_id=session_id, expected=True)
        self._bus.publish(CaptureWorkerStopped(session_id=session_id, pid=pid, expected=True))

    def start_watch(
        self, session_id_fn: Callable[[], str | None], on_crash: Callable[[], None]
    ) -> None:
        if self._watch_task is not None:
            return
        self._watch_task = asyncio.ensure_future(self._watch(session_id_fn, on_crash))

    def stop_watch(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None

    async def _watch(
        self, session_id_fn: Callable[[], str | None], on_crash: Callable[[], None]
    ) -> None:
        try:
            while True:
                await asyncio.sleep(_WATCH_INTERVAL_S)
                handle = self._capture
                if handle is not None and not handle.is_alive:
                    pid = handle.pid
                    self._capture = None
                    self._stop_frame_drain()
                    self._frame_queue = None
                    session_id = session_id_fn()
                    logger.warning("capture_worker_died_unexpectedly", pid=pid)
                    self._bus.publish(
                        CaptureWorkerStopped(session_id=session_id, pid=pid, expected=False)
                    )
                    on_crash()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------ #
    #  Frame descriptor draining: worker -> multiprocessing.Queue -> bus
    # ------------------------------------------------------------------ #

    def _start_frame_drain(self, session_id: str) -> None:
        self._drain_task = asyncio.ensure_future(self._drain_frames(session_id))

    def _stop_frame_drain(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            self._drain_task = None

    async def _drain_frames(self, session_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(_FRAME_DRAIN_INTERVAL_S)
                queue = self._frame_queue
                if queue is None:
                    continue
                while True:
                    try:
                        d = queue.get_nowait()
                    except queue_module.Empty:
                        break
                    self._bus.publish(
                        CaptureFrameAvailable(
                            session_id=session_id,
                            shm_name=d.shm_name,
                            slot=d.slot,
                            width=d.width,
                            height=d.height,
                            monitor_id=d.monitor_id,
                            frame_ts=d.frame_ts,
                            change_score=d.change_score,
                        )
                    )
        except asyncio.CancelledError:
            pass

    def shutdown(self, session_id: str | None = None) -> None:
        """App exit: guarantee no orphaned capture process, in any state."""
        self.stop_watch()
        self._stop_frame_drain()
        if self._capture is not None:
            self.kill_capture(session_id or "")
