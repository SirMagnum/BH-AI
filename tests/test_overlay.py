"""
Unit tests for Transparent Overlay Window (src/overlay.py).
Verifies:
  1. OverlayRect data attributes and default values.
  2. OCRBox spatial mapping and PII token red-flag detection.
  3. DFA state machine badge updates and alert messaging.
  4. Live streaming LLM response HUD banner accumulation and clearing.
  5. Thread-safe scheduling via after().
"""

import unittest
from unittest.mock import MagicMock

from src.ocr import OCRBox
from src.overlay import OverlayWindow, OverlayRect
from src.state_machine import State


class TestOverlayWindow(unittest.TestCase):

    def setUp(self):
        # Create a mock Tk root so tests run headlessly in CI without displaying physical windows
        self.mock_root = MagicMock()
        self.mock_root.winfo_screenwidth.return_value = 1920
        self.mock_root.winfo_screenheight.return_value = 1080

        # Execute scheduled callbacks immediately
        def immediate_after(delay, func, *args):
            func(*args)

        self.mock_root.after.side_effect = immediate_after
        self.overlay = OverlayWindow(self.mock_root)

    def test_overlay_rect_defaults(self):
        rect = OverlayRect(x=10, y=20, width=100, height=50)
        self.assertEqual(rect.x, 10)
        self.assertEqual(rect.y, 20)
        self.assertEqual(rect.width, 100)
        self.assertEqual(rect.height, 50)
        self.assertEqual(rect.color, "#38BDF8")
        self.assertEqual(rect.label, "")

    def test_build_region_rect(self):
        region = {"left": 100, "top": 150, "width": 800, "height": 600}
        rect = self.overlay.build_region_rect(region, hint="password")
        self.assertEqual(rect.x, 100)
        self.assertEqual(rect.y, 150)
        self.assertEqual(rect.width, 800)
        self.assertEqual(rect.height, 600)
        self.assertEqual(rect.color, "#F87171")

    def test_set_ocr_boxes_standard(self):
        box1 = OCRBox(text="Welcome to BH-AI", confidence=0.95, bbox=(50, 60, 200, 30))
        box2 = OCRBox(text="Settings Panel", confidence=0.88, bbox=(50, 100, 150, 30))

        self.overlay.set_ocr_boxes([box1, box2], region_offset=(10, 20))

        with self.overlay._lock:
            rects = self.overlay._rects

        self.assertEqual(len(rects), 2)
        self.assertEqual(rects[0].x, 60)  # 50 + 10
        self.assertEqual(rects[0].y, 80)  # 60 + 20
        self.assertEqual(rects[0].width, 200)
        self.assertEqual(rects[0].color, self.overlay.HINT_COLORS["search"])
        self.assertEqual(rects[0].label, "Welcome to BH-AI")

    def test_set_ocr_boxes_redacted_pii_highlighting(self):
        pii_box = OCRBox(
            text="User email: [EMAIL_ADDR_1]",
            confidence=0.99,
            bbox=(100, 200, 300, 40),
        )
        card_box = OCRBox(
            text="Payment: [CREDIT_CARD_1]",
            confidence=0.99,
            bbox=(100, 250, 300, 40),
        )

        self.overlay.set_ocr_boxes([pii_box, card_box])

        with self.overlay._lock:
            rects = self.overlay._rects

        self.assertEqual(len(rects), 2)
        # Redacted boxes should be red with [REDACTED] label
        for r in rects:
            self.assertEqual(r.color, self.overlay.HINT_COLORS["sensitive"])
            self.assertEqual(r.label, "[REDACTED]")

    def test_set_state_badge(self):
        # Test State.ACTIVE
        self.overlay.set_state_badge(State.ACTIVE)
        with self.overlay._lock:
            self.assertEqual(self.overlay._current_state, "active")
            self.assertEqual(self.overlay._state_alert, "")

        # Test State.PAUSED with blocklist alert
        self.overlay.set_state_badge(State.PAUSED, alert_msg="Bitwarden")
        with self.overlay._lock:
            self.assertEqual(self.overlay._current_state, "paused")
            self.assertEqual(self.overlay._state_alert, "Bitwarden")

    def test_streaming_llm_response_hud(self):
        self.overlay.show_llm_response("Hello, how can I help?", header="BH-AI")

        with self.overlay._lock:
            self.assertEqual(self.overlay._llm_text, "Hello, how can I help?")
            self.assertEqual(self.overlay._llm_header, "BH-AI")

        # Stream update chunk
        self.overlay.update_llm_stream(" Let me check your screen.")
        with self.overlay._lock:
            self.assertEqual(self.overlay._llm_text, "Hello, how can I help? Let me check your screen.")

        # Clear HUD
        self.overlay.clear_llm_response()
        with self.overlay._lock:
            self.assertEqual(self.overlay._llm_text, "")


if __name__ == "__main__":
    unittest.main()
