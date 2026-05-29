"""
BH-AI — Shared Theme and Custom Widgets
Provides a minimalist pastel color palette, modern typography,
and custom rounded widgets for Tkinter.
"""

import tkinter as tk

# ────────────────────────────── Colors ──────────────────────────────
# Soft, deep blue-grey minimalist theme with pastel accents.

C = {
    # Backgrounds
    "bg":          "#1E1E2E",  # Base deep blue-grey
    "surface":     "#181825",  # Slightly darker panels
    "panel":       "#11111B",  # Deepest background for contrast
    "border":      "#313244",  # Soft border lines

    # Pastel Accents
    "accent":      "#89B4FA",  # Pastel Blue
    "accent_hov":  "#B4BEFE",  # Lighter Blue for hover
    "success":     "#A6E3A1",  # Pastel Green
    "warning":     "#F9E2AF",  # Pastel Yellow
    "danger":      "#F38BA8",  # Pastel Red
    "dev":         "#FAB387",  # Pastel Peach (Dev badge)

    # Text
    "text":        "#CDD6F4",  # Soft White
    "muted":       "#A6ADC8",  # Soft Grey/Blue
    "dim":         "#45475A",  # Dark grey for disabled/hints

    # Special
    "transparent": "#010101",  # Used for transparency key on Windows
}

FONT_FAMILY = "Segoe UI"

def make_font(size: int, weight: str = "normal"):
    return (FONT_FAMILY, size, weight)


# ────────────────────────────── Custom Widgets ──────────────────────────────

def create_rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius=10, **kwargs):
    """Draw a rounded rectangle on a Tkinter canvas."""
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    """A custom Tkinter button with actual rounded corners via Canvas."""

    def __init__(self, parent, text: str, bg_color: str, fg_color: str,
                 command, radius=12, hover_color=None, padding_x=14, padding_y=6,
                 font=None, state=tk.NORMAL, **kwargs):
        super().__init__(parent, highlightthickness=0, bg=parent["bg"], **kwargs)

        self.text = text
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color or self._lighten(bg_color)
        self.command = command
        self.radius = radius
        self._state = state
        self.font = font or make_font(9, "bold")

        # Create elements
        self.rect_id = None
        self.text_id = None

        # Calculate sizing
        self._pad_x = padding_x
        self._pad_y = padding_y

        # Bind events
        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, width, height):
        self.delete("all")
        color = self.bg_color if self._state == tk.NORMAL else C["dim"]
        self.rect_id = create_rounded_rect(
            self, 2, 2, width - 2, height - 2,
            radius=self.radius, fill=color
        )
        self.text_id = self.create_text(
            width / 2, height / 2,
            text=self.text, fill=self.fg_color,
            font=self.font, justify=tk.CENTER
        )

    def _on_resize(self, event):
        self._draw(event.width, event.height)

    def _on_enter(self, event):
        if self._state == tk.NORMAL and self.rect_id:
            self.itemconfig(self.rect_id, fill=self.hover_color)

    def _on_leave(self, event):
        if self._state == tk.NORMAL and self.rect_id:
            self.itemconfig(self.rect_id, fill=self.bg_color)

    def _on_click(self, event):
        if self._state == tk.NORMAL and self.rect_id:
            self.itemconfig(self.rect_id, fill=self._darken(self.bg_color))

    def _on_release(self, event):
        if self._state == tk.NORMAL:
            # Check if mouse is still inside
            w = self.winfo_width()
            h = self.winfo_height()
            if 0 <= event.x <= w and 0 <= event.y <= h:
                self.itemconfig(self.rect_id, fill=self.hover_color)
                if self.command:
                    self.command()
            else:
                self.itemconfig(self.rect_id, fill=self.bg_color)

    def config_state(self, state):
        self._state = state
        if self.rect_id:
            color = self.bg_color if self._state == tk.NORMAL else C["dim"]
            self.itemconfig(self.rect_id, fill=color)

    def config_text(self, text):
        self.text = text
        if self.text_id:
            self.itemconfig(self.text_id, text=text)

    @staticmethod
    def _lighten(hex_color: str, factor: float = 0.15) -> str:
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return hex_color

    @staticmethod
    def _darken(hex_color: str, factor: float = 0.15) -> str:
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = max(0, int(r * (1 - factor)))
            g = max(0, int(g * (1 - factor)))
            b = max(0, int(b * (1 - factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        except:
            return hex_color
