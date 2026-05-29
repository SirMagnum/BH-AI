"""
Region Selector
A full-screen transparent overlay that lets the user drag-select a rectangle.
"""

import tkinter as tk


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
        win.attributes("-alpha", 0.25)
        win.configure(bg="black")
        win.grab_set()

        canvas = tk.Canvas(win, bg="black", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # Instructions label
        canvas.create_text(
            win.winfo_screenwidth() // 2,
            40,
            text="Click and drag to select the region to monitor.  Press Esc to cancel.",
            fill="white",
            font=("Segoe UI", 14, "bold"),
        )

        start_x = start_y = 0
        rect_id = None

        def on_press(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            rect_id = canvas.create_rectangle(
                start_x, start_y, start_x, start_y,
                outline="#00E5FF", width=2, dash=(6, 3),
            )

        def on_drag(event):
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

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
