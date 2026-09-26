"""
Unit tests for Wake-Word Detection and Push-To-Talk hotkey modules (src/voice/wakeword.py).
"""

import time
import unittest
from unittest.mock import MagicMock

from src.state_machine import StateMachine, State, Trigger
from src.voice.wakeword import (
    WakeWordDetector,
    PushToTalkManager,
    VoiceTriggerController,
)


class TestWakeWord(unittest.TestCase):

    def test_wakeword_detection_phrases(self):
        wake_events = []
        detector = WakeWordDetector(on_wake=lambda: wake_events.append(True))

        # Positive matches
        self.assertTrue(detector.check_phrase("Hey Assistant, what is on my screen?"))
        self.assertEqual(len(wake_events), 1)

        self.assertTrue(detector.check_phrase("Can you check this please, assistant?"))
        self.assertEqual(len(wake_events), 2)

        self.assertTrue(detector.check_phrase("Hello bhai, review this document."))
        self.assertEqual(len(wake_events), 3)

        # Negative matches
        self.assertFalse(detector.check_phrase("Just discussing regular topics."))
        self.assertEqual(len(wake_events), 3)

    def test_audio_frame_rms_energy(self):
        detector = WakeWordDetector()

        # Silent frame (zeros)
        silence = b"\x00" * 3200
        self.assertFalse(detector.process_audio_frame(silence, threshold_rms=300.0))

        # Loud frame (alternating high amplitude PCM)
        loud = b"\x7f\x7f" * 1600
        self.assertTrue(detector.process_audio_frame(loud, threshold_rms=100.0))

    def test_push_to_talk_manager(self):
        hotkey_events = []
        ptt = PushToTalkManager(on_hotkey=lambda: hotkey_events.append(True))

        # Start and stop daemon thread cleanly
        ptt.start()
        self.assertTrue(ptt._running)

        # Simulate hotkey trigger
        ptt.simulate_hotkey_press()
        self.assertEqual(len(hotkey_events), 1)

        ptt.stop()
        self.assertFalse(ptt._running)

    def test_voice_trigger_controller_state_machine_sync(self):
        sm = StateMachine()
        sm.trigger(Trigger.START)
        sm.trigger(Trigger.PAUSE)
        self.assertTrue(sm.is_paused)

        triggers_received = []
        controller = VoiceTriggerController(
            state_machine=sm,
            on_trigger=lambda trig_type: triggers_received.append(trig_type),
        )

        # Triggering wakeword should resume paused state machine
        controller.wakeword.check_phrase("Hey Assistant!")
        self.assertEqual(len(triggers_received), 1)
        self.assertEqual(triggers_received[0], "wakeword")
        self.assertEqual(sm.current_state, State.ACTIVE)

        # Triggering PTT hotkey
        controller.ptt.simulate_hotkey_press()
        self.assertEqual(len(triggers_received), 2)
        self.assertEqual(triggers_received[1], "hotkey")


if __name__ == "__main__":
    unittest.main()
