"""
Overlay Window Module
A transparent, always-on-top, click-through tkinter window that draws
spatial OCR highlight rectangles, DFA state badges, and live streaming
LLM reasoning HUD banners on the screen without blocking desktop clicks.
"""

from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass
class OverlayRect:
    x: int
    y: int
    width: int
    height: int
    color: str = "#38BDF8"  # Matches theme accent
    label: str = ""
    alpha: float = 0.45       # transparency of the fill


class OverlayWindow:
    """
    Draws a frameless, always-on-top transparent canvas over the desktop.
    Thread-safe; all rendering updates are scheduled via _root.after().
    """

    # Hint → colour mapping (consistent with graphite theme)
    HINT_COLORS = {
        "top":       "#F87171",   # Coral / Rose (danger)
        "form":      "#FBBF24",   # Amber (warning)
        "search":    "#38BDF8",   # Sky Cyan (accent)
        "password":  "#F87171",   # Coral / Rose (danger)
        "sensitive": "#F87171",   # Coral red for redacted PII
        "":          "#34D399",   # Mint / Emerald (success / default)
    }

    STATE_COLORS = {
        "active":      ("#34D399", "● OBSERVING"),      # Mint / Emerald
        "paused":      ("#FBBF24", "❚❚ PAUSED"),        # Amber
        "summarizing": ("#38BDF8", "✦ SUMMARIZING"),    # Sky Cyan
        "dormant":     ("#475569", "○ IDLE / DORMANT"), # Dim slate
    }

    def __init__(self, root: tk.Tk):
        self._root = root
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._visible = False
        self._rects: list[OverlayRect] = []
        self._lock = threading.Lock()

        # DFA state badge
        self._current_state: str | None = None
        self._state_alert: str = ""

        # LLM streaming HUD banner
        self._llm_text: str = ""
        self._llm_header: str = "BH-AI Assistant"

    # ------------------------------------------------------------------ #
    #  Public API (thread-safe, callable from any background worker)
    # ------------------------------------------------------------------ #

    def show(self) -> None:
        """Show the overlay window."""
        self._root.after(0, self._create_or_show)

    def hide(self) -> None:
        """Hide the overlay window."""
        self._root.after(0, self._hide_win)

    def set_rects(self, rects: list[OverlayRect]) -> None:
        """Set highlight rectangles to draw."""
        with self._lock:
            self._rects = list(rects)
        self._root.after(0, self._redraw)

    def clear(self) -> None:
        """Clear all active highlight rectangles."""
        with self._lock:
            self._rects = []
        self._root.after(0, self._redraw)

    def build_region_rect(self, region: dict, hint: str = "") -> OverlayRect:
        """Build an OverlayRect covering the captured region."""
        color = self.HINT_COLORS.get(hint, self.HINT_COLORS[""])
        return OverlayRect(
            x=region["left"],
            y=region["top"],
            width=region["width"],
            height=region["height"],
            color=color,
            label="Monitored Region",
        )

    # ------------------------------------------------------------------ #
    #  Spatial OCRBox & PII Redaction Mapping
    # ------------------------------------------------------------------ #

    def set_ocr_boxes(
        self,
        boxes: Sequence[Any],
        region_offset: tuple[int, int] = (0, 0),
    ) -> None:
        """
        Converts spatial OCRBox objects into screen-space OverlayRects.
        Redacted PII tokens receive prominent red warning borders.
        """
        rects: list[OverlayRect] = []
        ox, oy = region_offset

        for box in boxes:
            text = getattr(box, "text", "")
            bbox = getattr(box, "bbox", (0, 0, 0, 0))
            if not bbox or len(bbox) < 4:
                continue

            bx, by, bw, bh = bbox
            if bw <= 0 or bh <= 0:
                continue

            # Detect if this OCR box contains local PII redaction tokens
            is_redacted = any(
                token in text for token in (
                    "[EMAIL_ADDR_",
                    "[PHONE_NUM_",
                    "[CREDIT_CARD_",
                    "[API_KEY_",
                    "[CREDENTIALS_",
                    "[SSN_",
                    "[IP_ADDR_",
                    "[REDACTED]",
                )
            )

            color = self.HINT_COLORS["sensitive"] if is_redacted else self.HINT_COLORS["search"]
            label = "[REDACTED]" if is_redacted else (text[:20] if len(text) > 0 else "")

            rects.append(
                OverlayRect(
                    x=bx + ox,
                    y=by + oy,
                    width=bw,
                    height=bh,
                    color=color,
                    label=label,
                )
            )

        self.set_rects(rects)

    # ------------------------------------------------------------------ #
    #  DFA State Machine Badge
    # ------------------------------------------------------------------ #

    def set_state_badge(self, state: Any, alert_msg: str = "") -> None:
        """
        Updates the floating DFA state badge rendered on the overlay.
        :param state: State enum or state string ('active', 'paused', etc.)
        :param alert_msg: Optional contextual message (e.g. 'Blocklist: Bitwarden')
        """
        with self._lock:
            self._current_state = str(getattr(state, "value", state)).lower()
            self._state_alert = alert_msg
        self._root.after(0, self._redraw)

    # ------------------------------------------------------------------ #
    #  Live Streaming LLM HUD Response Banner
    # ------------------------------------------------------------------ #

    def show_llm_response(self, text: str, header: str = "BH-AI Assistant") -> None:
        """Display an LLM response banner on the transparent overlay."""
        with self._lock:
            self._llm_text = text
            self._llm_header = header
        self._root.after(0, self._redraw)

    def update_llm_stream(self, chunk: str, header: str = "BH-AI Assistant") -> None:
        """Append streamed tokens to the LLM response HUD banner."""
        with self._lock:
            self._llm_text += chunk
            self._llm_header = header
        self._root.after(0, self._redraw)

    def append_llm_chunk(self, chunk: str) -> None:
        """Append a streamed chunk to the LLM HUD banner."""
        with self._lock:
            self._llm_text += chunk
        self._root.after(0, self._redraw)

    def clear_llm_response(self) -> None:
        """Dismiss and clear the LLM HUD response banner."""
        with self._lock:
            self._llm_text = ""
            self._llm_header = "BH-AI Assistant"
        self._root.after(0, self._redraw)

    # ------------------------------------------------------------------ #
    #  Internal (main Tkinter thread only)
    # ------------------------------------------------------------------ #

    def _create_or_show(self) -> None:
        if self._win is None:
            self._win = tk.Toplevel(self._root)
            self._win.overrideredirect(True)        # no title bar
            self._win.attributes("-topmost", True)
            self._win.attributes("-alpha", 0.01)    # near-transparent root
            self._win.attributes("-transparentcolor", "black")
            self._win.configure(bg="black")

            # Full virtual screen size
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            self._win.geometry(f"{sw}x{sh}+0+0")

            self._canvas = tk.Canvas(
                self._win,
                bg="black",
                highlightthickness=0,
            )
            self._canvas.pack(fill=tk.BOTH, expand=True)

            # Make window click-through on Windows
            self._make_click_through()

        self._win.deiconify()
        self._win.lift()
        self._visible = True
        self._redraw()

    def _hide_win(self) -> None:
        if self._win:
            self._win.withdraw()
        self._visible = False

    def _redraw(self) -> None:
        if not self._canvas or not self._visible:
            return
        self._canvas.delete("all")

        with self._lock:
            rects = list(self._rects)
            state_key = self._current_state
            alert_msg = self._state_alert
            llm_text = self._llm_text
            llm_header = self._llm_header

        _font_ui = "Segoe UI"

        # 1. Draw spatial highlight rectangles
        for r in rects:
            x1, y1 = r.x, r.y
            x2, y2 = r.x + r.width, r.y + r.height

            # Border rectangle
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=r.color,
                width=2,
                dash=(6, 3),
            )

            # Corner accents
            accent_size = 14
            for sx, sy, ex, ey in [
                (x1, y1, x1 + accent_size, y1),
                (x1, y1, x1, y1 + accent_size),
                (x2 - accent_size, y2, x2, y2),
                (x2, y2 - accent_size, x2, y2),
            ]:
                self._canvas.create_line(
                    sx, sy, ex, ey,
                    fill=r.color, width=3,
                )

            # Label badge
            if r.label:
                pad = 4
                label_x = x1 + pad
                label_y = max(y1 - 18, 4)
                badge_w = min(len(r.label) * 7 + pad * 2, 220)

                self._canvas.create_rectangle(
                    label_x - pad, label_y - 2,
                    label_x + badge_w, label_y + 14,
                    fill=r.color, outline="",
                )
                self._canvas.create_text(
                    label_x, label_y + 6,
                    text=r.label,
                    anchor="w",
                    fill="black",
                    font=(_font_ui, 8, "bold"),
                )

        # 2. Draw DFA State Machine Badge (top right)
        if state_key and state_key in self.STATE_COLORS:
            color, label_text = self.STATE_COLORS[state_key]
            if alert_msg:
                label_text = f"{label_text} ({alert_msg})"

            badge_x = self._root.winfo_screenwidth() - 260
            badge_y = 24
            badge_w = 230
            badge_h = 32

            # Background pill (graphite dark)
            self._canvas.create_rectangle(
                badge_x, badge_y,
                badge_x + badge_w, badge_y + badge_h,
                fill="#16181D", outline=color, width=2,
            )
            # Status text
            self._canvas.create_text(
                badge_x + 12, badge_y + 16,
                text=label_text,
                anchor="w",
                fill=color,
                font=(_font_ui, 9, "bold"),
            )

        # 3. Draw Streaming LLM HUD Response Banner (bottom-center)
        if llm_text:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()

            banner_w = min(max(int(sw * 0.6), 500), 900)
            banner_h = 130
            bx1 = (sw - banner_w) // 2
            by1 = sh - banner_h - 60
            bx2 = bx1 + banner_w
            by2 = by1 + banner_h

            # Glassmorphic dark card (graphite palette)
            self._canvas.create_rectangle(
                bx1, by1, bx2, by2,
                fill="#0D0E11", outline="#38BDF8", width=2,
            )
            # Accent top header bar
            self._canvas.create_rectangle(
                bx1, by1, bx2, by1 + 26,
                fill="#16181D", outline="",
            )
            # Header text
            self._canvas.create_text(
                bx1 + 16, by1 + 13,
                text=f"✦ {llm_header}",
                anchor="w",
                fill="#38BDF8",
                font=(_font_ui, 9, "bold"),
            )
            # Streamed body text
            self._canvas.create_text(
                bx1 + 16, by1 + 38,
                text=llm_text,
                anchor="nw",
                fill="#F1F5F9",
                width=banner_w - 32,
                font=(_font_ui, 10),
            )

    def _make_click_through(self) -> None:
        """Use Win32 API to make the overlay window click-through."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            # WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20)
        except Exception as exc:
            # Harmless in test/headless environments
            pass
