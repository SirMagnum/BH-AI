"""
Shared colour palette — ported from the prototype's `src/ui_theme.py`.

The palette itself is platform-neutral and worth keeping; the tkinter
`RoundedButton` canvas widget is not — Qt gets rounded corners from a
stylesheet `border-radius`, so nothing there needed porting.

Also carries the ambient-truthfulness colours from roadmap §2.4: "the
tray icon and overlay border must visually reflect state (grey = idle,
blue = active, amber = paused)."
"""

from __future__ import annotations

from bhai.session.states import SessionState

C = {
    "bg": "#1E1E2E",
    "surface": "#181825",
    "panel": "#11111B",
    "border": "#313244",
    "accent": "#89B4FA",
    "accent_hover": "#B4BEFE",
    "success": "#A6E3A1",
    "warning": "#F9E2AF",
    "danger": "#F38BA8",
    "dev": "#FAB387",
    "text": "#CDD6F4",
    "muted": "#A6ADC8",
    "dim": "#45475A",
}

FONT_FAMILY = "Helvetica Neue, Segoe UI, sans-serif"

# roadmap §2.4: grey = idle, blue = active, amber = paused. Ending/terminal
# states get their own tone so the tray never lies about what's happening.
STATE_COLOR = {
    SessionState.IDLE: C["dim"],
    SessionState.ACTIVE: C["accent"],
    SessionState.PAUSED: C["warning"],
    SessionState.ENDING: C["muted"],
    SessionState.SAVED: C["success"],
    SessionState.DISCARDED: C["dim"],
}

STATE_LABEL = {
    SessionState.IDLE: "Idle",
    SessionState.ACTIVE: "Active — watching",
    SessionState.PAUSED: "Paused",
    SessionState.ENDING: "Ending…",
    SessionState.SAVED: "Saved",
    SessionState.DISCARDED: "Discarded",
}


def button_style(bg: str, fg: str = C["text"]) -> str:
    return f"""
        QPushButton {{
            background-color: {bg};
            color: {fg};
            border: none;
            border-radius: 10px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {_lighten(bg)}; }}
        QPushButton:pressed {{ background-color: {_darken(bg)}; }}
        QPushButton:disabled {{ background-color: {C["dim"]}; color: {C["muted"]}; }}
    """


def window_style() -> str:
    return f"background-color: {C['bg']}; color: {C['text']};"


def _lighten(hex_color: str, factor: float = 0.15) -> str:
    r, g, b = _rgb(hex_color)
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, factor: float = 0.15) -> str:
    r, g, b = _rgb(hex_color)
    r = max(0, int(r * (1 - factor)))
    g = max(0, int(g * (1 - factor)))
    b = max(0, int(b * (1 - factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (
        int(hex_color[1:3], 16),
        int(hex_color[3:5], 16),
        int(hex_color[5:7], 16),
    )
