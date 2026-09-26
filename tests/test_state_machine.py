"""
Unit tests for the Deterministic Finite Automaton (DFA) State Machine.
"""

import threading
import unittest
from src.state_machine import (
    StateMachine,
    State,
    Trigger,
    InvalidStateTransitionError,
    TransitionRecord,
)


class TestStateMachine(unittest.TestCase):

    def setUp(self):
        self.sm = StateMachine()

    def test_initial_state_is_dormant(self):
        self.assertEqual(self.sm.current_state, State.DORMANT)
        self.assertTrue(self.sm.is_dormant)
        self.assertFalse(self.sm.is_active)
        self.assertFalse(self.sm.is_paused)
        self.assertFalse(self.sm.is_summarizing)

    def test_valid_lifecycle_transitions(self):
        # DORMANT -> START -> ACTIVE
        self.sm.trigger(Trigger.START)
        self.assertEqual(self.sm.current_state, State.ACTIVE)
        self.assertTrue(self.sm.is_active)

        # ACTIVE -> PAUSE -> PAUSED
        self.sm.trigger(Trigger.PAUSE)
        self.assertEqual(self.sm.current_state, State.PAUSED)
        self.assertTrue(self.sm.is_paused)

        # PAUSED -> RESUME -> ACTIVE
        self.sm.trigger(Trigger.RESUME)
        self.assertEqual(self.sm.current_state, State.ACTIVE)

        # ACTIVE -> STOP -> DORMANT
        self.sm.trigger(Trigger.STOP)
        self.assertEqual(self.sm.current_state, State.DORMANT)

    def test_privacy_block_match_transition(self):
        self.sm.trigger(Trigger.START)
        self.assertEqual(self.sm.current_state, State.ACTIVE)

        # Privacy engine detects blocked app/window -> immediate hard-pause
        self.sm.trigger(Trigger.BLOCK_MATCH, payload={"window": "1Password"})
        self.assertEqual(self.sm.current_state, State.PAUSED)

        # History should record payload
        history = self.sm.get_history()
        self.assertEqual(history[-1].trigger, Trigger.BLOCK_MATCH)
        self.assertEqual(history[-1].payload, {"window": "1Password"})

    def test_idle_timeout_transitions(self):
        # From ACTIVE -> TIMEOUT -> DORMANT
        self.sm.trigger(Trigger.START)
        self.sm.trigger(Trigger.TIMEOUT)
        self.assertEqual(self.sm.current_state, State.DORMANT)

        # From PAUSED -> TIMEOUT -> DORMANT
        self.sm.trigger(Trigger.START)
        self.sm.trigger(Trigger.PAUSE)
        self.sm.trigger(Trigger.TIMEOUT)
        self.assertEqual(self.sm.current_state, State.DORMANT)

    def test_summarizing_flow(self):
        self.sm.trigger(Trigger.START)
        self.sm.trigger(Trigger.SUMMARIZE)
        self.assertEqual(self.sm.current_state, State.SUMMARIZING)
        self.assertTrue(self.sm.is_summarizing)

        self.sm.trigger(Trigger.STOP)
        self.assertEqual(self.sm.current_state, State.DORMANT)

    def test_invalid_transitions_raise_error(self):
        # DORMANT cannot PAUSE or RESUME
        with self.assertRaises(InvalidStateTransitionError) as ctx:
            self.sm.trigger(Trigger.PAUSE)
        self.assertEqual(ctx.exception.current_state, State.DORMANT)
        self.assertEqual(ctx.exception.trigger, Trigger.PAUSE)

        with self.assertRaises(InvalidStateTransitionError):
            self.sm.trigger(Trigger.RESUME)

        # Once ACTIVE, cannot START again
        self.sm.trigger(Trigger.START)
        with self.assertRaises(InvalidStateTransitionError):
            self.sm.trigger(Trigger.START)

    def test_can_trigger_and_try_trigger(self):
        # In DORMANT
        self.assertTrue(self.sm.can_trigger(Trigger.START))
        self.assertTrue(self.sm.can_trigger(Trigger.STOP))
        self.assertFalse(self.sm.can_trigger(Trigger.PAUSE))
        self.assertFalse(self.sm.can_trigger(Trigger.RESUME))

        # try_trigger should return False instead of raising
        self.assertFalse(self.sm.try_trigger(Trigger.PAUSE))
        self.assertEqual(self.sm.current_state, State.DORMANT)

        # try_trigger should succeed for valid transition
        self.assertTrue(self.sm.try_trigger(Trigger.START))
        self.assertEqual(self.sm.current_state, State.ACTIVE)

    def test_get_valid_triggers(self):
        valid = self.sm.get_valid_triggers()
        self.assertIn(Trigger.START, valid)
        self.assertIn(Trigger.STOP, valid)
        self.assertNotIn(Trigger.PAUSE, valid)

        self.sm.trigger(Trigger.START)
        active_valid = self.sm.get_valid_triggers()
        self.assertIn(Trigger.PAUSE, active_valid)
        self.assertIn(Trigger.BLOCK_MATCH, active_valid)
        self.assertIn(Trigger.TIMEOUT, active_valid)
        self.assertIn(Trigger.STOP, active_valid)
        self.assertNotIn(Trigger.START, active_valid)

    def test_listeners_notification(self):
        events = []

        def on_transition(src, dst, trig, payload):
            events.append((src, dst, trig, payload))

        self.sm.add_listener(on_transition)
        self.sm.trigger(Trigger.START, payload="test_run")
        self.sm.trigger(Trigger.PAUSE)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], (State.DORMANT, State.ACTIVE, Trigger.START, "test_run"))
        self.assertEqual(events[1], (State.ACTIVE, State.PAUSED, Trigger.PAUSE, None))

        # Remove listener
        self.sm.remove_listener(on_transition)
        self.sm.trigger(Trigger.RESUME)
        self.assertEqual(len(events), 2)

    def test_listener_exception_resilience(self):
        def buggy_listener(src, dst, trig, payload):
            raise RuntimeError("Failure in external observer")

        self.sm.add_listener(buggy_listener)
        # Exception inside listener should not prevent state transition
        new_state = self.sm.trigger(Trigger.START)
        self.assertEqual(new_state, State.ACTIVE)
        self.assertEqual(self.sm.current_state, State.ACTIVE)

    def test_thread_safety(self):
        # Stress test concurrent triggers
        num_threads = 10
        errors = []

        def worker():
            for _ in range(100):
                # Try valid and invalid triggers randomly
                self.sm.try_trigger(Trigger.START)
                self.sm.try_trigger(Trigger.PAUSE)
                self.sm.try_trigger(Trigger.RESUME)
                self.sm.try_trigger(Trigger.STOP)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # State should be valid Enum value
        self.assertIn(self.sm.current_state, [State.DORMANT, State.ACTIVE, State.PAUSED, State.SUMMARIZING])
        self.assertTrue(len(self.sm.get_history()) > 0)


if __name__ == "__main__":
    unittest.main()
