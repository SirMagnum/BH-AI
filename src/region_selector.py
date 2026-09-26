"""
Region Selector
A full-screen transparent overlay that lets the user drag-select a rectangle.
Features a tinted selection fill, live dimension readout, and theme-consistent styling.
"""

import tkinter as tk
from src.ui_theme import C, make_font


class RegionSelector:
    """
    Displays a full-screen screenshot-overlay so the user can rubber-band
    select a screen region.  Returns (x, y, w, h) in screen coordinates.
    """

    def __init__(self, root: tk.Tk):
        self._root = root
        self.result: dict | None = None

    def select(self) -> dict | None:
        """Block until the user selects a region, then return it."""
        self.result = None
        self._run()
        return self.result

    def _run(self):
        win = tk.Toplevel(self._root)
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.30)
        win.configure(bg="#0D0E11")
        win.grab_set()

        canvas = tk.Canvas(win, bg="#0D0E11", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # Instructions label with graphite styling
        canvas.create_text(
            win.winfo_screenwidth() // 2,
            40,
            text="Click and drag to select the region to monitor  ·  Press Esc to cancel",
            fill=C["text"],
            font=make_font(13, "bold"),
        )

        start_x = start_y = 0
        rect_id = None
        fill_id = None
        dim_id = None

        def on_press(event):
            nonlocal start_x, start_y, rect_id, fill_id, dim_id
            start_x, start_y = event.x, event.y

            # Tinted fill overlay
            fill_id = canvas.create_rectangle(
                start_x, start_y, start_x, start_y,
                fill=C["accent"], outline="", stipple="gray25",
            )
            # Selection border
            rect_id = canvas.create_rectangle(
                start_x, start_y, start_x, start_y,
                outline=C["accent"], width=2, dash=(6, 3),
            )
            # Live dimension readout
            dim_id = canvas.create_text(
                start_x, start_y - 16,
                text="0 × 0",
                fill=C["accent"], font=make_font(10, "bold"),
                anchor="sw",
            )

        def on_drag(event):
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)
            if fill_id:
                canvas.coords(fill_id, start_x, start_y, event.x, event.y)
            if dim_id:
                w = abs(event.x - start_x)
                h = abs(event.y - start_y)
                # Position dimension label near top-left of selection
                lx = min(start_x, event.x) + 6
                ly = min(start_y, event.y) - 8
                canvas.coords(dim_id, lx, ly)
                canvas.itemconfig(dim_id, text=f"{w} × {h} px")

        def on_release(event):
            x1 = min(start_x, event.x)
            y1 = min(start_y, event.y)
            x2 = max(start_x, event.x)
            y2 = max(start_y, event.y)
            if (x2 - x1) > 10 and (y2 - y1) > 10:
                self.result = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
            win.grab_release()
            win.destroy()

        def on_escape(event):
            win.grab_release()
            win.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        win.bind("<Escape>", on_escape)

        win.wait_window()
