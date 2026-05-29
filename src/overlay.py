"""
Overlay Window Module
A transparent, always-on-top, click-through tkinter window that draws
highlight rectangles on the screen without blocking user interaction.
"""

import tkinter as tk
import threading
from dataclasses import dataclass


@dataclass
class OverlayRect:
    x: int
    y: int
    width: int
    height: int
    color: str = "#00E5FF"
    label: str = ""
    alpha: float = 0.45       # transparency of the fill


class OverlayWindow:
    """
    Draws a frameless, always-on-top transparent canvas over the desktop.
    Runs in the main tkinter thread; updates are posted via after().
    """

    # Hint → colour mapping
    HINT_COLORS = {
        "top":      "#FF6B6B",   # red-ish
        "form":     "#FFC107",   # amber
        "search":   "#00E5FF",   # cyan
        "password": "#FF4081",   # pink-red
        "":         "#69F0AE",   # green (default)
    }

    def __init__(self, root: tk.Tk):
        self._root = root
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._visible = False
        self._rects: list[OverlayRect] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Public API (call from any thread)
    # ------------------------------------------------------------------ #

    def show(self):
        self._root.after(0, self._create_or_show)

    def hide(self):
        self._root.after(0, self._hide_win)

    def set_rects(self, rects: list[OverlayRect]):
        with self._lock:
            self._rects = rects
        self._root.after(0, self._redraw)

    def clear(self):
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
    #  Internal (main-thread only)
    # ------------------------------------------------------------------ #

    def _create_or_show(self):
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

    def _hide_win(self):
        if self._win:
            self._win.withdraw()
        self._visible = False

    def _redraw(self):
        if not self._canvas or not self._visible:
            return
        self._canvas.delete("all")

        with self._lock:
            rects = list(self._rects)

        for r in rects:
            x1, y1 = r.x, r.y
            x2, y2 = r.x + r.width, r.y + r.height

            # Border rectangle
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                outline=r.color,
                width=3,
                dash=(8, 4),
            )

            # Corner accents (top-left / bottom-right)
            accent_size = 16
            for sx, sy, ex, ey in [
                (x1, y1, x1 + accent_size, y1),
                (x1, y1, x1, y1 + accent_size),
                (x2 - accent_size, y2, x2, y2),
                (x2, y2 - accent_size, x2, y2),
            ]:
                self._canvas.create_line(
                    sx, sy, ex, ey,
                    fill=r.color, width=4,
                )

            # Label badge
            if r.label:
                pad = 6
                label_x = x1 + pad
                label_y = y1 - 22

                self._canvas.create_rectangle(
                    label_x - pad, label_y - 4,
                    label_x + len(r.label) * 7 + pad, label_y + 16,
                    fill=r.color, outline="",
                )
                self._canvas.create_text(
                    label_x, label_y + 6,
                    text=r.label,
                    anchor="w",
                    fill="black",
                    font=("Segoe UI", 9, "bold"),
                )

    def _make_click_through(self):
        """Use Win32 API to make the overlay window click-through."""
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(
                self._win.winfo_id()
            )
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            # WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x80000 | 0x20)
        except Exception as exc:
            print(f"[Overlay] Click-through not applied: {exc}")
