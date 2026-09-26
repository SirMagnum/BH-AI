"""
Deterministic Finite Automaton (DFA) State Machine for BH-AI.
Governs observation lifecycle, privacy gating, and OS handle lifecycle.

Formal specification:
  S = <Q, Σ, δ, q0, F>
  Q = {DORMANT, ACTIVE, PAUSED, SUMMARIZING}
  Σ = {START, PAUSE, RESUME, TIMEOUT, BLOCK_MATCH, STOP, SUMMARIZE}
  q0 = DORMANT
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("BH-AI.StateMachine")


class State(str, enum.Enum):
    """
    Q: Set of DFA states.
    """
    DORMANT = "dormant"          # q_dormant: Idle / offline. All screen capture and OS handles released.
    ACTIVE = "active"            # q_active: Opt-in continuous observation & OCR active.
    PAUSED = "paused"            # q_paused: Hard-pause (user or privacy blocklist). Handles revoked.
    SUMMARIZING = "summarizing"  # q_summarizing: Generating session summary or RAG consolidation.

    def __str__(self) -> str:
        return self.value


class Trigger(str, enum.Enum):
    """
    Σ: Set of transition input symbols / triggers.
    """
    START = "start"              # σ_start: User initiates observation.
    PAUSE = "pause"              # σ_pause: User manually pauses observation.
    RESUME = "resume"            # σ_resume: User manually resumes observation.
    TIMEOUT = "timeout"          # σ_timeout: Inactivity watchdog timer fires.
    BLOCK_MATCH = "block_match"  # σ_block_match: Privacy engine detects blacklisted window/URL.
    STOP = "stop"                # σ_stop: Terminate observation session.
    SUMMARIZE = "summarize"      # σ_summarize: Begin session consolidation.

    def __str__(self) -> str:
        return self.value


class InvalidStateTransitionError(Exception):
    """Raised when an illegal transition is attempted in the DFA."""

    def __init__(self, current_state: State, trigger: Trigger, message: str | None = None):
        self.current_state = current_state
        self.trigger = trigger
        msg = message or f"Illegal DFA transition: cannot apply trigger '{trigger.value}' from state '{current_state.value}'."
        super().__init__(msg)


@dataclass(frozen=True)
class TransitionRecord:
    """Audit log entry for state transitions."""
    timestamp: float
    source_state: State
    target_state: State
    trigger: Trigger
    payload: Any = None


# δ: Q × Σ -> Q (Deterministic Transition Function)
_TRANSITION_TABLE: dict[tuple[State, Trigger], State] = {
    # From DORMANT (q0)
    (State.DORMANT, Trigger.START): State.ACTIVE,
    (State.DORMANT, Trigger.STOP): State.DORMANT,  # Idempotent stop

    # From ACTIVE
    (State.ACTIVE, Trigger.PAUSE): State.PAUSED,
    (State.ACTIVE, Trigger.BLOCK_MATCH): State.PAUSED,
    (State.ACTIVE, Trigger.TIMEOUT): State.DORMANT,
    (State.ACTIVE, Trigger.STOP): State.DORMANT,
    (State.ACTIVE, Trigger.SUMMARIZE): State.SUMMARIZING,

    # From PAUSED
    (State.PAUSED, Trigger.RESUME): State.ACTIVE,
    (State.PAUSED, Trigger.TIMEOUT): State.DORMANT,
    (State.PAUSED, Trigger.STOP): State.DORMANT,
    (State.PAUSED, Trigger.SUMMARIZE): State.SUMMARIZING,

    # From SUMMARIZING
    (State.SUMMARIZING, Trigger.STOP): State.DORMANT,
    (State.SUMMARIZING, Trigger.TIMEOUT): State.DORMANT,
    (State.SUMMARIZING, Trigger.RESUME): State.ACTIVE,
}


StateCallback = Callable[[State, State, Trigger, Any], None]


class StateMachine:
    """
    Deterministic Finite Automaton engine for managing BH-AI lifecycle.
    Thread-safe with state transition hooks and audit logging.
    """

    def __init__(self, initial_state: State = State.DORMANT):
        self._state: State = initial_state
        self._lock = threading.RLock()
        self._listeners: list[StateCallback] = []
        self._history: list[TransitionRecord] = []
        self._max_history = 1000

    # ------------------------------------------------------------------ #
    #  State Inspection
    # ------------------------------------------------------------------ #

    @property
    def current_state(self) -> State:
        with self._lock:
            return self._state

    @property
    def is_dormant(self) -> bool:
        with self._lock:
            return self._state == State.DORMANT

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._state == State.ACTIVE

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._state == State.PAUSED

    @property
    def is_summarizing(self) -> bool:
        with self._lock:
            return self._state == State.SUMMARIZING

    def can_trigger(self, trigger: Trigger) -> bool:
        """Check if trigger is valid from current state without executing."""
        with self._lock:
            return (self._state, trigger) in _TRANSITION_TABLE

    def get_valid_triggers(self) -> list[Trigger]:
        """Return list of valid triggers from current state."""
        with self._lock:
            return [
                trig for (st, trig) in _TRANSITION_TABLE.keys()
                if st == self._state
            ]

    def get_history(self) -> list[TransitionRecord]:
        """Return a snapshot of transition history."""
        with self._lock:
            return list(self._history)

    # ------------------------------------------------------------------ #
    #  Subscriptions & Listeners
    # ------------------------------------------------------------------ #

    def add_listener(self, callback: StateCallback) -> None:
        """
        Register a callback: fn(source_state, target_state, trigger, payload).
        """
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: StateCallback) -> None:
        """Unregister a listener callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    # ------------------------------------------------------------------ #
    #  Transitions
    # ------------------------------------------------------------------ #

    def trigger(self, trigger: Trigger, payload: Any = None) -> State:
        """
        Execute a deterministic transition δ(current_state, trigger).
        Raises InvalidStateTransitionError if the transition is illegal.
        Returns the new State.
        """
        with self._lock:
            source = self._state
            key = (source, trigger)

            if key not in _TRANSITION_TABLE:
                raise InvalidStateTransitionError(source, trigger)

            target = _TRANSITION_TABLE[key]
            self._state = target

            record = TransitionRecord(
                timestamp=time.time(),
                source_state=source,
                target_state=target,
                trigger=trigger,
                payload=payload,
            )
            self._history.append(record)
            if len(self._history) > self._max_history:
                self._history.pop(0)

            listeners_snapshot = list(self._listeners)

        # Notify listeners outside the lock to avoid deadlock risks
        for listener in listeners_snapshot:
            try:
                listener(source, target, trigger, payload)
            except Exception as exc:
                logger.error(f"Error in state listener {listener}: {exc}", exc_info=True)

        return target

    def try_trigger(self, trigger: Trigger, payload: Any = None) -> bool:
        """
        Attempt transition without raising InvalidStateTransitionError.
        Returns True if transition occurred, False if invalid.
        """
        with self._lock:
            if not self.can_trigger(trigger):
                return False

        try:
            self.trigger(trigger, payload)
            return True
        except InvalidStateTransitionError:
            return False

    def reset(self) -> None:
        """Force-reset the state machine back to DORMANT."""
        with self._lock:
            self._state = State.DORMANT
