"""
BH-AI — Shared Theme and Custom Widgets
Minimalist Slate / Graphite industrial palette (strictly zero purple tint),
modern typography, rounded styling, and CustomTkinter fallback shims.
"""

import math
import sys
import tkinter as tk
from tkinter import ttk

# ────────────────────────────── Colors ──────────────────────────────
# Clean minimalist slate & graphite palette

C = {
    # Surfaces & Canvas
    "bg":          "#0D0E11",  # Deep obsidian black
    "surface":     "#16181D",  # Clean slate grey container
    "panel":       "#1C1F26",  # Elevated panel fill
    "panel_alt":   "#232730",  # Card / input fields
    "border":      "#2B303C",  # Subdued edge stroke
    "border_focus":"#404756",  # Highlighted edge

    # Monochromatic Accents (Cool Slate / Arctic White)
    "accent":      "#38BDF8",  # Crisp Sky / Cyan accent
    "accent_hov":  "#7DD3FC",  # Light cyan hover
    "accent_dim":  "#1E3A5F",  # Dimmed accent for backgrounds
    "dev":         "#94A3B8",  # Industrial slate badge

    # Functional Indicators
    "success":     "#34D399",  # Mint / Emerald
    "warning":     "#FBBF24",  # Amber
    "danger":      "#F87171",  # Coral / Rose

    # Typography
    "text":        "#F1F5F9",  # Bright slate white
    "muted":       "#94A3B8",  # Neutral grey
    "dim":         "#475569",  # Dim slate

    # Special
    "transparent": "#010101",  # Transparency key on Windows

    # Log-level tints (subtle background highlight for alternating rows)
    "row_even":    "#16181D",  # Same as surface
    "row_odd":     "#1A1D24",  # Slightly lighter
}

# ────────────────────────────── Typography ──────────────────────────

FONT_FAMILY = (
    "Segoe UI" if sys.platform.startswith("win")
    else "SF Pro Display" if sys.platform == "darwin"
    else "DejaVu Sans"
)

FONT_MONO = (
    "Cascadia Code" if sys.platform.startswith("win")
    else "SF Mono" if sys.platform == "darwin"
    else "DejaVu Sans Mono"
)

def make_font(size: int, weight: str = "normal"):
    return (FONT_FAMILY, size, weight)

def make_mono(size: int, weight: str = "normal"):
    return (FONT_MONO, size, weight)

# ────────────────────────────── Spacing ─────────────────────────────

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}

# ────────────────────────────── Color Utilities ─────────────────────

def _parse_hex(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

def lerp_color(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two hex colors. t=0 → c1, t=1 → c2."""
    r1, g1, b1 = _parse_hex(c1)
    r2, g2, b2 = _parse_hex(c2)
    t = max(0.0, min(1.0, t))
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"

def gen_sine_pulse(c_active: str, c_bg: str, steps: int) -> list[str]:
    """Generate smooth sine-interpolated pulse gradient between active & low states."""
    r1, g1, b1 = _parse_hex(c_active)
    r2, g2, b2 = _parse_hex(c_bg)

    colors = []
    for i in range(steps):
        factor = (math.sin((i / steps) * 2 * math.pi) + 1) / 2
        factor = 0.25 + 0.75 * factor  # Dampen bottom floor
        nr = int(r2 + (r1 - r2) * factor)
        ng = int(g2 + (g1 - g2) * factor)
        nb = int(b2 + (b1 - b2) * factor)
        colors.append(f"#{nr:02x}{ng:02x}{nb:02x}")
    return colors


# ────────────────────────────── Drawing Helpers ─────────────────────

def create_rounded_rect(canvas, x1, y1, x2, y2, radius=10, **kwargs):
    """Draw a smooth rounded rectangle on a Tkinter canvas."""
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


# ────────────────────────────── Widget Factory Helpers ──────────────

def make_card(parent, **kwargs):
    """Create a standard card frame with consistent styling."""
    return ctk.CTkFrame(parent, fg_color=C["surface"], corner_radius=8, **kwargs)


def make_card_header(parent, title: str, icon: str = ""):
    """Build a standard card header row with optional icon and separator."""
    header = ctk.CTkFrame(parent, fg_color=C["surface"], height=36)
    header.pack(fill=tk.X, padx=SPACING["lg"], pady=(SPACING["sm"] + 2, 0))

    label_text = f"{icon}  {title}" if icon else title
    ctk.CTkLabel(
        header, text=label_text, text_color=C["text"],
        fg_color=C["surface"], font=make_font(10, "bold"),
    ).pack(side=tk.LEFT)

    make_separator(parent)
    return header


def make_separator(parent, color: str = None):
    """Create a subtle horizontal divider line."""
    ctk.CTkFrame(
        parent, fg_color=color or C["border"], height=1,
    ).pack(fill=tk.X, pady=SPACING["sm"])


# ────────────────────────────── ttk Dark Mode Styling ──────────────

def style_combobox_dark(root):
    """Apply dark-mode styling to ttk Combobox widgets."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        "Dark.TCombobox",
        fieldbackground=C["panel_alt"],
        background=C["panel_alt"],
        foreground=C["text"],
        bordercolor=C["border"],
        arrowcolor=C["accent"],
        selectbackground=C["accent_dim"],
        selectforeground=C["text"],
        relief="flat",
    )
    style.map("Dark.TCombobox",
        fieldbackground=[("readonly", C["panel_alt"]), ("focus", C["panel_alt"])],
        background=[("active", C["border_focus"])],
        bordercolor=[("focus", C["accent"])],
        foreground=[("readonly", C["text"])],
    )

    # Style the dropdown listbox
    try:
        root.option_add("*TCombobox*Listbox.background", C["panel_alt"])
        root.option_add("*TCombobox*Listbox.foreground", C["text"])
        root.option_add("*TCombobox*Listbox.selectBackground", C["accent_dim"])
        root.option_add("*TCombobox*Listbox.selectForeground", C["text"])
        root.option_add("*TCombobox*Listbox.font", make_font(10))
    except Exception:
        pass

    return "Dark.TCombobox"


def style_scale_dark(root):
    """Apply dark-mode styling to ttk Scale widgets."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        "Dark.Horizontal.TScale",
        background=C["surface"],
        troughcolor=C["panel"],
        sliderrelief="flat",
        borderwidth=0,
        sliderlength=16,
    )
    style.map("Dark.Horizontal.TScale",
        background=[("active", C["surface"])],
    )

    return "Dark.Horizontal.TScale"


# ────────────────────────────── Log Level Icons ────────────────────

LOG_ICONS = {
    "INFO": "●",
    "OK":   "✓",
    "WARN": "▲",
    "ERR":  "✕",
    "DEV":  "◆",
}


# ────────────────────────────── CustomTkinter Setup ──────────────────────────────

try:
    import customtkinter as ctk
    HAS_CUSTOMTKINTER = True
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    class RoundedButton(ctk.CTkButton):
        def __init__(self, master=None, **kwargs):
            if "bg_color" in kwargs and "fg_color" not in kwargs:
                kwargs["fg_color"] = kwargs.pop("bg_color")
            kwargs.pop("padding_x", None)
            kwargs.pop("padding_y", None)
            if "radius" in kwargs and "corner_radius" not in kwargs:
                kwargs["corner_radius"] = kwargs.pop("radius")
            super().__init__(master=master, **kwargs)

        def config_state(self, state):
            self.configure(state="normal" if state in ("normal", "active") else "disabled")

        def config_text(self, text):
            self.configure(text=text)

except ImportError:
    HAS_CUSTOMTKINTER = False

    class _CTkShim:
        @staticmethod
        def set_appearance_mode(*args, **kwargs): pass
        @staticmethod
        def set_default_color_theme(*args, **kwargs): pass

        class CTk(tk.Tk):
            def __init__(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                super().__init__(*args, **kwargs)
                self.configure(bg=C["bg"])

            def configure(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                super().configure(*args, **kwargs)

        class CTkFrame(tk.Frame):
            def __init__(self, master=None, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                kwargs.pop("corner_radius", None)
                kwargs.setdefault("bg", C["surface"])
                super().__init__(master=master, **kwargs)

            def configure(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                kwargs.pop("corner_radius", None)
                super().configure(*args, **kwargs)

        class CTkLabel(tk.Label):
            def __init__(self, master=None, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                kwargs.pop("corner_radius", None)
                kwargs.setdefault("bg", getattr(master, "cget", lambda x: C["surface"])("bg") if master else C["surface"])
                kwargs.setdefault("fg", C["text"])
                super().__init__(master=master, **kwargs)

            def configure(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                kwargs.pop("corner_radius", None)
                super().configure(*args, **kwargs)

        class CTkButton(tk.Button):
            def __init__(self, master=None, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                    kwargs.setdefault("activebackground", kwargs["bg"])
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                    kwargs.setdefault("activeforeground", kwargs["fg"])
                kwargs.pop("hover_color", None)
                kwargs.pop("corner_radius", None)
                kwargs.setdefault("relief", "flat")
                kwargs.setdefault("cursor", "hand2")
                super().__init__(master=master, **kwargs)

            def configure(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs["bg"] = kwargs.pop("fg_color")
                    kwargs.setdefault("activebackground", kwargs["bg"])
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                    kwargs.setdefault("activeforeground", kwargs["fg"])
                kwargs.pop("hover_color", None)
                kwargs.pop("corner_radius", None)
                super().configure(*args, **kwargs)

        class CTkCheckBox(tk.Checkbutton):
            def __init__(self, master=None, **kwargs):
                if "fg_color" in kwargs:
                    kwargs.pop("fg_color")
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                kwargs.pop("hover_color", None)
                kwargs.setdefault("bg", C["surface"])
                kwargs.setdefault("selectcolor", C["panel"])
                kwargs.setdefault("activebackground", C["surface"])
                kwargs.setdefault("activeforeground", C["accent"])
                super().__init__(master=master, **kwargs)

            def configure(self, *args, **kwargs):
                if "fg_color" in kwargs:
                    kwargs.pop("fg_color")
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                super().configure(*args, **kwargs)

    ctk = _CTkShim()
    RoundedButton = ctk.CTkButton