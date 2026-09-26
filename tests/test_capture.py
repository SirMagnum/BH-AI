"""
Unit tests for the refactored ScreenCapture daemon.
Verifies DFA StateMachine integration, OS handle lifecycle management, and inactivity watchdog.
"""

import time
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from src.capture import ScreenCapture
from src.state_machine import StateMachine, State, Trigger


class TestScreenCapture(unittest.TestCase):

    def setUp(self):
        self.sm = StateMachine()
        # Mock mss.mss so we do not actually invoke native OS screen grabs in headless tests
        self.mock_mss_patch = patch("src.capture.mss.mss")
        self.mock_mss_class = self.mock_mss_patch.start()

        # Setup mock grab return value
        self.mock_sct_instance = MagicMock()
        self.mock_grab_result = MagicMock()
        self.mock_grab_result.size = (10, 10)
        self.mock_grab_result.bgra = b"\x00" * 400
        self.mock_sct_instance.grab.return_value = self.mock_grab_result
        self.mock_mss_class.return_value = self.mock_sct_instance

    def tearDown(self):
        self.mock_mss_patch.stop()

    def test_initial_state(self):
        cap = ScreenCapture(state_machine=self.sm)
        self.assertEqual(cap.state_machine.current_state, State.DORMANT)
        self.assertFalse(cap.is_running)
        self.assertFalse(cap.is_paused)
        self.assertFalse(cap.has_active_handle)
        self.assertIsNone(cap.latest_frame)

    def test_start_pause_resume_stop_lifecycle(self):
        cap = ScreenCapture(
            region={"left": 0, "top": 0, "width": 10, "height": 10},
            fps=10.0,
            state_machine=self.sm,
            idle_timeout_seconds=None,
        )

        cap.start()
        self.assertEqual(self.sm.current_state, State.ACTIVE)
        self.assertTrue(cap.is_running)

        # Allow worker loop to run a tick
        time.sleep(0.15)
        self.assertTrue(cap.has_active_handle)
        self.assertIsNotNone(cap.latest_frame)

        # Pause
        cap.pause()
        self.assertEqual(self.sm.current_state, State.PAUSED)
        self.assertFalse(cap.is_running)
        self.assertTrue(cap.is_paused)
        # Handle must be explicitly disposed
        self.assertFalse(cap.has_active_handle)
        self.mock_sct_instance.close.assert_called()

        # Resume
        cap.resume()
        self.assertEqual(self.sm.current_state, State.ACTIVE)
        self.assertTrue(cap.is_running)
        time.sleep(0.15)
        self.assertTrue(cap.has_active_handle)

        # Stop
        cap.stop()
        self.assertEqual(self.sm.current_state, State.DORMANT)
        self.assertFalse(cap.is_running)
        self.assertFalse(cap.has_active_handle)
        self.assertIsNone(cap.latest_frame)

    def test_external_privacy_trigger_disposes_handle(self):
        cap = ScreenCapture(
            region={"left": 0, "top": 0, "width": 10, "height": 10},
            fps=10.0,
            state_machine=self.sm,
            idle_timeout_seconds=None,
        )
        cap.start()
        time.sleep(0.15)
        self.assertTrue(cap.has_active_handle)

        # External actor (e.g. privacy monitor) triggers BLOCK_MATCH
        self.sm.trigger(Trigger.BLOCK_MATCH, payload={"app": "KeePass"})
        self.assertEqual(self.sm.current_state, State.PAUSED)

        # Handle should be disposed immediately by listener
        self.assertFalse(cap.has_active_handle)
        cap.stop()

    def test_frame_callback_invoked(self):
        frames_received = []

        def callback(img):
            frames_received.append(img)

        cap = ScreenCapture(
            region={"left": 0, "top": 0, "width": 10, "height": 10},
            fps=20.0,
            state_machine=self.sm,
            idle_timeout_seconds=None,
        )
        cap.set_callback(callback)
        cap.start()

        time.sleep(0.2)
        cap.stop()

        self.assertGreater(len(frames_received), 0)
        self.assertIsInstance(frames_received[0], Image.Image)

    def test_inactivity_watchdog(self):
        # Short timeout of 0.3 seconds for test
        cap = ScreenCapture(
            region=None,  # No region to simulate idle state without frames
            fps=10.0,
            state_machine=self.sm,
            idle_timeout_seconds=0.3,
        )
        cap.start()
        self.assertEqual(self.sm.current_state, State.ACTIVE)

        # Wait for watchdog to trigger TIMEOUT
        time.sleep(0.9)
        self.assertEqual(self.sm.current_state, State.DORMANT)
        self.assertFalse(cap.is_running)
        self.assertFalse(cap.has_active_handle)


if __name__ == "__main__":
    unittest.main()
