"""
Unit tests for the Window & Domain Blocklist Engine.
"""

import time
import unittest
from unittest.mock import MagicMock

from src.privacy.blocklist import (
    BlocklistConfig,
    BlocklistMatch,
    WindowBlocklistMonitor,
    get_foreground_window_info,
)
from src.state_machine import StateMachine, State, Trigger


class TestBlocklist(unittest.TestCase):

    def setUp(self):
        self.config = BlocklistConfig()
        self.sm = StateMachine()

    def test_default_app_matching(self):
        # Sensitive password managers and private chat apps
        match = self.config.is_match(window_title="My Vault", app_name="1Password.exe")
        self.assertIsNotNone(match)
        self.assertEqual(match.reason, "app")
        self.assertEqual(match.pattern, "1password")

        match2 = self.config.is_match(window_title="Chat", app_name="Signal.exe")
        self.assertIsNotNone(match2)
        self.assertEqual(match2.pattern, "signal")

    def test_default_title_matching(self):
        match = self.config.is_match(window_title="Chase Online Banking - Chrome", app_name="chrome.exe")
        self.assertIsNotNone(match)
        self.assertEqual(match.reason, "title")

        match_login = self.config.is_match(window_title="Sign In to Your Account", app_name="firefox.exe")
        self.assertIsNotNone(match_login)

    def test_safe_window_does_not_match(self):
        match = self.config.is_match(window_title="index.py - VS Code", app_name="code.exe")
        self.assertIsNone(match)

        match2 = self.config.is_match(window_title="Calculator", app_name="calc.exe")
        self.assertIsNone(match2)

    def test_dynamic_add_and_remove_rules(self):
        self.config.add_app("blender")
        self.assertIsNotNone(self.config.is_match("3D Scene", "blender.exe"))

        self.config.remove_app("blender")
        self.assertIsNone(self.config.is_match("3D Scene", "blender.exe"))

        self.config.add_title_pattern("top secret")
        self.assertIsNotNone(self.config.is_match("Top Secret Project", "notepad.exe"))

        self.config.remove_title_pattern("top secret")
        self.assertIsNone(self.config.is_match("Top Secret Project", "notepad.exe"))

    def test_foreground_window_info_callable(self):
        # Ensure system call does not crash
        title, app = get_foreground_window_info()
        self.assertIsInstance(title, str)
        self.assertIsInstance(app, str)

    def test_monitor_triggers_hard_pause_on_block_match(self):
        # Setup mock inspector returning blocked window
        mock_inspector = MagicMock(return_value=("Bitwarden - Password Manager", "bitwarden.exe"))

        monitor = WindowBlocklistMonitor(
            state_machine=self.sm,
            config=self.config,
            window_inspector=mock_inspector,
        )

        # Start session
        self.sm.trigger(Trigger.START)
        self.assertEqual(self.sm.current_state, State.ACTIVE)

        # Inspect window
        match = monitor.check_now()
        self.assertIsNotNone(match)
        self.assertEqual(match.pattern, "bitwarden")

        # State machine should have transitioned immediately to PAUSED
        self.assertEqual(self.sm.current_state, State.PAUSED)
        self.assertTrue(self.sm.is_paused)

        # History should contain BLOCK_MATCH trigger and metadata payload
        history = self.sm.get_history()
        self.assertEqual(history[-1].trigger, Trigger.BLOCK_MATCH)
        self.assertEqual(history[-1].payload["window"], "Bitwarden - Password Manager")
        self.assertEqual(history[-1].payload["app"], "bitwarden.exe")

    def test_monitor_background_thread_start_stop(self):
        mock_inspector = MagicMock(return_value=("Harmless Window", "notepad.exe"))
        monitor = WindowBlocklistMonitor(
            state_machine=self.sm,
            poll_interval=0.1,
            window_inspector=mock_inspector,
        )

        self.sm.trigger(Trigger.START)
        monitor.start()
        self.assertTrue(monitor._running)

        time.sleep(0.25)
        self.assertEqual(self.sm.current_state, State.ACTIVE)

        monitor.stop()
        self.assertFalse(monitor._running)


if __name__ == "__main__":
    unittest.main()
