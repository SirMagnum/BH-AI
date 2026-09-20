"""
Session / Privacy state machine — the trust root of the whole product.

A session is the unit of BOTH memory scope and privacy scope (roadmap §2.1).
That coupling is deliberate and must never drift apart: "what the AI can
remember" and "what the AI is allowed to see" are the same concept here.

    IDLE ──start──► ACTIVE ──pause──► PAUSED ──resume──► ACTIVE
                       │                  │
                       ├───worker_crashed─┤   (capture died unexpectedly)
                       │                  │
                       └──────end─────────┴──► ENDING ──► SAVED | DISCARDED

Non-negotiable rule this module exists to enforce: no capture *process* may
exist in IDLE or PAUSED. This module does not itself own the worker process
(SessionManager does — see manager.py) but every transition it accepts is
exactly the set of moments at which the capture worker is allowed to be
spawned or must be killed. There is no other path to a legal state change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDING = "ending"
    SAVED = "saved"
    DISCARDED = "discarded"


class SessionEvent(StrEnum):
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    END = "end"
    SAVE = "save"
    DISCARD = "discard"
    # Capture worker died unexpectedly while ACTIVE. This is NOT the same
    # as PAUSE (user intent) but lands in the same state, because "we lost
    # the capture handle" and "the user asked us to stop looking" must have
    # identical consequences downstream. Silently respawning capture here
    # would be exactly the kind of bypass invariant 1 forbids.
    WORKER_CRASHED = "worker_crashed"


class IllegalTransitionError(Exception):
    """Raised when an event is not legal in the current state.

    There is deliberately no fallback behaviour here — a caller hitting
    this is a bug, not a degraded path, and must be fixed at the call site.
    """

    def __init__(self, state: SessionState, event: SessionEvent):
        self.state = state
        self.event = event
        super().__init__(f"illegal transition: {event.value!r} is not valid from {state.value!r}")


# The exhaustive transition table. Any (state, event) pair not present here
# is illegal. This table IS the specification — do not special-case around
# it elsewhere in the codebase.
_TRANSITIONS: dict[tuple[SessionState, SessionEvent], SessionState] = {
    (SessionState.IDLE, SessionEvent.START): SessionState.ACTIVE,
    (SessionState.ACTIVE, SessionEvent.PAUSE): SessionState.PAUSED,
    (SessionState.ACTIVE, SessionEvent.WORKER_CRASHED): SessionState.PAUSED,
    (SessionState.PAUSED, SessionEvent.RESUME): SessionState.ACTIVE,
    (SessionState.ACTIVE, SessionEvent.END): SessionState.ENDING,
    (SessionState.PAUSED, SessionEvent.END): SessionState.ENDING,
    (SessionState.ENDING, SessionEvent.SAVE): SessionState.SAVED,
    (SessionState.ENDING, SessionEvent.DISCARD): SessionState.DISCARDED,
}

# States in which a capture worker process is permitted to exist.
# Everything downstream that spawns/kills the worker keys off this set —
# there must be exactly one source of truth for "capture is allowed now".
CAPTURE_ALLOWED_STATES = frozenset({SessionState.ACTIVE})

# Terminal states — no legal event moves out of these. A new session means
# a new SessionFSM instance, never resetting one in place.
TERMINAL_STATES = frozenset({SessionState.SAVED, SessionState.DISCARDED})


@dataclass
class SessionFSM:
    """Pure state machine — no I/O, no process management, no persistence.

    Deliberately dumb: this class only knows what states and events exist
    and what the legal transitions between them are. It is the thing
    property-tests iterate over. SessionManager wraps this and does the
    actual work (spawning workers, writing to SQLite, publishing events).
    """

    state: SessionState = SessionState.IDLE

    def can(self, event: SessionEvent) -> bool:
        return (self.state, event) in _TRANSITIONS

    def apply(self, event: SessionEvent) -> SessionState:
        key = (self.state, event)
        if key not in _TRANSITIONS:
            raise IllegalTransitionError(self.state, event)
        self.state = _TRANSITIONS[key]
        return self.state

    def legal_events(self) -> frozenset[SessionEvent]:
        return frozenset(evt for (st, evt) in _TRANSITIONS if st == self.state)

    @property
    def capture_allowed(self) -> bool:
        return self.state in CAPTURE_ALLOWED_STATES

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
