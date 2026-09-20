"""
SessionManager — the single owner of session state.

`_reconcile_capture()` is THE enforcement point for invariant 1. It is
called after every legal transition and keys strictly off
`fsm.capture_allowed`: capture-worker existence tracks that boolean,
nothing else. No other function in this codebase may call
`WorkerSupervisor.spawn_capture` / `kill_capture` — SessionManager is the
only holder of the supervisor.

This is the direct fix for the prototype's [`src/capture.py`](../../src/capture.py)
`pause()`, which sets a flag while the `mss` handle stays open. Here,
PAUSE is not reachable without the capture process actually dying first.
"""

from __future__ import annotations

import structlog

from bhai.bus.bus import EventBus
from bhai.bus.events import ErrorEvent, SessionStateChanged
from bhai.capture.region_store import RegionStore
from bhai.db.store import SessionStore
from bhai.platform.portable.capture_mss import get_monitor_signature
from bhai.session.states import (
    IllegalTransitionError,
    SessionEvent,
    SessionFSM,
    SessionState,
)
from bhai.session.supervisor import WorkerSupervisor

logger = structlog.get_logger(__name__)

_DEFAULT_MONITOR_ID = "1"  # single-monitor default; multi-monitor selection is a later Phase 2 item


class SessionManager:
    def __init__(
        self,
        bus: EventBus,
        store: SessionStore,
        region_store: RegionStore | None = None,
    ) -> None:
        self._bus = bus
        self._store = store
        self._region_store = region_store
        self._fsm = SessionFSM()
        self._supervisor = WorkerSupervisor(bus)
        self._session_id: str | None = None
        self._supervisor.start_watch(lambda: self._session_id, self._on_capture_crashed)

    @property
    def state(self) -> SessionState:
        return self._fsm.state

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def capture_pid(self) -> int | None:
        return self._supervisor.capture_pid

    def can(self, event: SessionEvent) -> bool:
        return self._fsm.can(event)

    # ------------------------------------------------------------------ #
    #  User-facing actions — each is one FSM event plus reconciliation
    # ------------------------------------------------------------------ #

    def start(self) -> str:
        if self._fsm.state != SessionState.IDLE:
            raise IllegalTransitionError(self._fsm.state, SessionEvent.START)
        self._session_id = self._store.create_session()
        self._transition(SessionEvent.START, reason="user_start")
        return self._session_id

    def pause(self) -> None:
        self._transition(SessionEvent.PAUSE, reason="user_pause")

    def resume(self) -> None:
        self._transition(SessionEvent.RESUME, reason="user_resume")

    def end(self) -> None:
        self._transition(SessionEvent.END, reason="user_end")

    def finish(self, save: bool) -> None:
        """Terminal action after end(): SAVE or DISCARD. Resets to a fresh
        FSM afterward — a session is one-shot, never reset in place."""
        event = SessionEvent.SAVE if save else SessionEvent.DISCARD
        self._transition(event, reason="user_save" if save else "user_discard")
        session_id = self._session_id
        assert session_id is not None
        if save:
            self._store.mark_saved(session_id)
        else:
            self._store.discard_session(session_id)
        self._session_id = None
        self._fsm = SessionFSM()

    def shutdown(self) -> None:
        """App exit: guarantee no orphaned capture process regardless of state."""
        self._supervisor.shutdown(self._session_id)

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #

    def _transition(self, event: SessionEvent, reason: str) -> None:
        session_id = self._session_id
        assert session_id is not None
        old = self._fsm.state
        new = self._fsm.apply(event)  # raises IllegalTransitionError if not legal
        self._store.update_state(session_id, new)
        self._store.record_event(session_id, event.value, {"reason": reason})
        self._bus.publish(
            SessionStateChanged(session_id=session_id, old_state=old, new_state=new, reason=reason)
        )
        logger.info(
            "session_transition",
            session_id=session_id,
            fsm_event=event.value,
            old=old.value,
            new=new.value,
        )
        self._reconcile_capture()

    def _reconcile_capture(self) -> None:
        session_id = self._session_id
        assert session_id is not None
        if self._fsm.capture_allowed and not self._supervisor.capture_alive:
            regions = self._resolve_watch_regions(_DEFAULT_MONITOR_ID)
            self._supervisor.spawn_capture(
                session_id, monitor_id=_DEFAULT_MONITOR_ID, watch_regions=regions
            )
        elif not self._fsm.capture_allowed and self._supervisor.capture_alive:
            self._supervisor.kill_capture(session_id)

    def _resolve_watch_regions(self, monitor_id: str) -> list:
        """Look up whatever regions the user has allowed for the monitor
        we're about to capture. No RegionStore configured, or nothing
        saved for this exact resolution -> empty list, which per
        `apply_watch_regions` means the capture worker sees a fully black
        frame. That is the safe default (§2.4), not a fallback to "see
        everything" — we never guess or rescale an old region onto a
        resolution it wasn't drawn for."""
        if self._region_store is None:
            return []
        try:
            signature = get_monitor_signature(monitor_id)
        except ValueError:
            logger.warning("monitor_signature_lookup_failed", monitor_id=monitor_id)
            return []
        return self._region_store.list_for(signature)

    def _on_capture_crashed(self) -> None:
        if self._fsm.state != SessionState.ACTIVE:
            return  # already paused/ended by the time we heard about it
        self._transition(SessionEvent.WORKER_CRASHED, reason="capture_worker_died_unexpectedly")
        self._bus.publish(
            ErrorEvent(
                session_id=self._session_id,
                category="degradable",
                message="Capture stopped unexpectedly; session paused.",
            )
        )
