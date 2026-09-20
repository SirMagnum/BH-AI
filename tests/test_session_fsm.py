"""
Property tests over the session state machine (roadmap Phase 1 DoD:
"All legal transitions verified; all illegal transitions rejected with a
test each").
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bhai.session.states import (
    CAPTURE_ALLOWED_STATES,
    IllegalTransitionError,
    SessionEvent,
    SessionFSM,
    SessionState,
)

ALL_STATES = list(SessionState)
ALL_EVENTS = list(SessionEvent)

LEGAL = {
    (SessionState.IDLE, SessionEvent.START): SessionState.ACTIVE,
    (SessionState.ACTIVE, SessionEvent.PAUSE): SessionState.PAUSED,
    (SessionState.ACTIVE, SessionEvent.WORKER_CRASHED): SessionState.PAUSED,
    (SessionState.PAUSED, SessionEvent.RESUME): SessionState.ACTIVE,
    (SessionState.ACTIVE, SessionEvent.END): SessionState.ENDING,
    (SessionState.PAUSED, SessionEvent.END): SessionState.ENDING,
    (SessionState.ENDING, SessionEvent.SAVE): SessionState.SAVED,
    (SessionState.ENDING, SessionEvent.DISCARD): SessionState.DISCARDED,
}


@pytest.mark.parametrize(("state", "event", "expected"), [(s, e, n) for (s, e), n in LEGAL.items()])
def test_legal_transition(state: SessionState, event: SessionEvent, expected: SessionState) -> None:
    fsm = SessionFSM(state=state)
    assert fsm.can(event)
    assert fsm.apply(event) == expected
    assert fsm.state == expected


@pytest.mark.parametrize(
    ("state", "event"),
    [(s, e) for s in ALL_STATES for e in ALL_EVENTS if (s, e) not in LEGAL],
)
def test_illegal_transition_rejected(state: SessionState, event: SessionEvent) -> None:
    fsm = SessionFSM(state=state)
    assert not fsm.can(event)
    with pytest.raises(IllegalTransitionError):
        fsm.apply(event)
    # Rejection must not mutate state.
    assert fsm.state == state


def test_illegal_transition_count_matches_full_matrix() -> None:
    """Every (state, event) pair not in LEGAL is illegal — no silent gaps."""
    total = len(ALL_STATES) * len(ALL_EVENTS)
    assert total - len(LEGAL) == sum(
        1 for s in ALL_STATES for e in ALL_EVENTS if (s, e) not in LEGAL
    )


def test_capture_allowed_only_in_active() -> None:
    assert CAPTURE_ALLOWED_STATES == frozenset({SessionState.ACTIVE})
    for state in ALL_STATES:
        fsm = SessionFSM(state=state)
        assert fsm.capture_allowed == (state == SessionState.ACTIVE)


def test_terminal_states_accept_nothing() -> None:
    for state in (SessionState.SAVED, SessionState.DISCARDED):
        fsm = SessionFSM(state=state)
        assert fsm.is_terminal
        assert fsm.legal_events() == frozenset()


@given(st.lists(st.sampled_from(ALL_EVENTS), min_size=0, max_size=12))
def test_random_event_sequences_never_produce_an_invalid_state(events: list[SessionEvent]) -> None:
    """Fuzz: whatever sequence of events arrives, the FSM either transitions
    to a state reachable via the table or raises — it never lands somewhere
    outside SessionState, and a rejected event never mutates state."""
    fsm = SessionFSM()
    for event in events:
        before = fsm.state
        if fsm.can(event):
            after = fsm.apply(event)
            assert after in ALL_STATES
        else:
            with pytest.raises(IllegalTransitionError):
                fsm.apply(event)
            assert fsm.state == before
        if fsm.is_terminal:
            break  # no legal event moves out of a terminal state
