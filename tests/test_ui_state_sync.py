"""
Unit tests verifying UI state synchronization with the DFA State Machine.
"""

import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from src.state_machine import StateMachine, State, Trigger
from src.ui import AssistantUI
from src.ui_user import UserModeUI


class TestUIStateSync(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.destroy()
            cls.has_tk = True
        except Exception:
            cls.has_tk = False

    @classmethod
    def tearDownClass(cls):
        pass

    def _cleanup_app(self, app):
        if hasattr(app, "db") and hasattr(app.db, "close"):
            try:
                app.db.close()
            except Exception:
                pass
        if hasattr(app, "root") and app.root:
            try:
                for aid in app.root.tk.eval("after info").split():
                    try:
                        app.root.after_cancel(aid)
                    except Exception:
                        pass
                app.root.update_idletasks()
                app.root.destroy()
            except Exception:
                pass

    def test_assistant_ui_state_sync(self):
        if not self.has_tk:
            self.skipTest("Tkinter display not available")

        # Mock UI building and periodic loops so window isn't rendered
        with patch.object(AssistantUI, "_build_ui"), \
             patch.object(AssistantUI, "_apply_style"), \
             patch.object(AssistantUI, "_tick"), \
             patch.object(AssistantUI, "_on_frame"):
            app = AssistantUI()
            app.root.withdraw()

            app._state_badge = MagicMock()
            app._status_lbl = MagicMock()
            app._update_session_buttons = MagicMock()
            app._log = MagicMock()
            app.overlay = MagicMock()

            # 1. Simulate ACTIVE transition
            app._apply_dfa_state(State.DORMANT, State.ACTIVE, Trigger.START)
            self.assertTrue(app._session_active)
            self.assertFalse(app._paused)
            app._state_badge.configure.assert_called_with(text="[ACTIVE]", text_color=unittest.mock.ANY)

            # 2. Simulate privacy BLOCK_MATCH
            app._apply_dfa_state(State.ACTIVE, State.PAUSED, Trigger.BLOCK_MATCH, payload={"window": "Bitwarden"})
            self.assertTrue(app._paused)
            app.overlay.hide.assert_called()
            app._status_lbl.configure.assert_called()
            app._log.assert_called_with("Window blocklist matched: (Bitwarden)", "WARN")

            # 3. Simulate watchdog TIMEOUT
            app._apply_dfa_state(State.PAUSED, State.DORMANT, Trigger.TIMEOUT)
            self.assertFalse(app._session_active)
            self.assertFalse(app._paused)
            app.overlay.clear.assert_called()
            app._state_badge.configure.assert_called_with(text="[DORMANT]", text_color=unittest.mock.ANY)

            self._cleanup_app(app)

    def test_user_mode_ui_state_sync(self):
        if not self.has_tk:
            self.skipTest("Tkinter display not available")

        with patch.object(UserModeUI, "_build_pill"), \
             patch.object(UserModeUI, "_make_draggable"), \
             patch.object(UserModeUI, "_refresh_windows"), \
             patch.object(UserModeUI, "_tick"):
            app = UserModeUI()
            app.root.withdraw()

            app._set_state = MagicMock()
            app._set_status = MagicMock()
            app._update_btns = MagicMock()
            app.overlay = MagicMock()

            # Active
            app._apply_dfa_state(State.DORMANT, State.ACTIVE, Trigger.START)
            app._set_state.assert_called_with("active")
            self.assertTrue(app._session_active)

            # Block match
            app._apply_dfa_state(State.ACTIVE, State.PAUSED, Trigger.BLOCK_MATCH, payload={"app": "1Password"})
            app._set_state.assert_called_with("paused")
            app._set_status.assert_called_with("Auto-paused (Privacy) (1Password)")

            # Timeout
            app._apply_dfa_state(State.PAUSED, State.DORMANT, Trigger.TIMEOUT)
            app._set_state.assert_called_with("idle")
            app._set_status.assert_called_with("Auto-stopped (Idle timeout)")

            self._cleanup_app(app)

    def test_assistant_ui_frame_processing_and_redaction(self):
        if not self.has_tk:
            self.skipTest("Tkinter display not available")

        with patch.object(AssistantUI, "_build_ui"), \
             patch.object(AssistantUI, "_apply_style"), \
             patch.object(AssistantUI, "_tick"):
            app = AssistantUI()
            app.root.withdraw()

            app._session_active = True
            app._current_session_id = "test_sync_session"
            app._region = {"left": 0, "top": 0, "width": 800, "height": 600}
            app.db = MagicMock()
            app.ocr = MagicMock()
            app.pii = MagicMock()
            app.overlay = MagicMock()
            app._append_ocr = MagicMock()
            app._update_insights = MagicMock()
            app._render_preview = MagicMock()
            app._fps_meter_lbl = MagicMock()
            app._frame_count_lbl = MagicMock()

            # Mock OCR box extraction
            mock_box = MagicMock()
            mock_box.text = "user email is test@company.com"
            app.ocr.extract_boxes.return_value = [mock_box]

            mock_pii_res = MagicMock()
            mock_pii_res.redacted_text = "user email is [EMAIL_ADDR_1]"
            app.pii.redact_text.return_value = mock_pii_res
            app.pii.redact_boxes.return_value = ([mock_box], [])

            mock_img = MagicMock()
            app._on_frame(mock_img)

            # Verify PII redactor sanitized the text
            app.pii.redact_text.assert_called()
            # Verify record was stored to episodic memory
            app.db.add_record.assert_called_with(
                session_id="test_sync_session",
                redacted_text="user email is [EMAIL_ADDR_1]",
                app_name=unittest.mock.ANY,
                window_title=unittest.mock.ANY,
                is_active=True,
                token_count=unittest.mock.ANY,
            )

            self._cleanup_app(app)

    def test_assistant_ui_submit_query(self):
        if not self.has_tk:
            self.skipTest("Tkinter display not available")

        with patch.object(AssistantUI, "_build_ui"), \
             patch.object(AssistantUI, "_apply_style"), \
             patch.object(AssistantUI, "_tick"):
            app = AssistantUI()
            app.root.withdraw()

            app.llm = MagicMock()
            app.llm.stream_with_rag.return_value = iter(["Local ", "response ", "generated."])
            app._current_session_id = "session_query_test"
            app._llm_response_text = MagicMock()
            app._ask_btn = MagicMock()
            app.overlay = MagicMock()

            app._submit_query("What did I work on?")
            time.sleep(0.15)  # Allow worker thread to yield tokens
            app._drain_llm_queue()
            app._is_llm_streaming = False

            app.llm.stream_with_rag.assert_called_with("What did I work on?", app.rag, session_id="session_query_test")
            app.overlay.show_llm_response.assert_called()

            self._cleanup_app(app)

    def test_user_mode_ui_voice_trigger(self):
        if not self.has_tk:
            self.skipTest("Tkinter display not available")

        with patch.object(UserModeUI, "_build_pill"), \
             patch.object(UserModeUI, "_make_draggable"), \
             patch.object(UserModeUI, "_refresh_windows"), \
             patch.object(UserModeUI, "_tick"):
            app = UserModeUI()
            app.root.withdraw()

            app.llm = MagicMock()
            app.llm.stream_with_rag.return_value = iter(["Screen ", "activity ", "summary."])
            app._current_session_id = "user_mode_sess"
            app.overlay = MagicMock()
            app._set_status = MagicMock()

            app._handle_voice_trigger("push_to_talk")
            time.sleep(0.15)  # Allow worker thread
            app._drain_llm_queue()
            app._is_llm_streaming = False

            app.llm.stream_with_rag.assert_called()
            app.overlay.show_llm_response.assert_called()

            self._cleanup_app(app)


if __name__ == "__main__":
    unittest.main()
