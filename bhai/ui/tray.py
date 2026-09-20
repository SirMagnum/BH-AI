"""
System tray icon — reflects session state colour.

Roadmap §2.4: "the tray icon and overlay border must visually reflect
state (grey = idle, blue = active, amber = paused). Ambient truthfulness
beats a settings page." The icon is drawn programmatically (a coloured
dot) rather than shipping image assets, so there is nothing to keep in
sync between an icon file and the palette in theme.py.

The dot carries a white-then-black double ring so it stays visible
against BOTH light and dark menu bars — a flat colour fill alone can
disappear entirely against a similarly-toned bar, which is the likely
reason this was hard to spot in early testing. This tray icon is a
convenience now, not the only way in: `DashboardWindow` has its own
buttons for the inspector and watch-area editor (see main_window.py).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from bhai.session.states import SessionState
from bhai.ui.theme import STATE_COLOR, STATE_LABEL


def _draw_dot(size: int, color: str) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size // 6
    d = size - 2 * margin

    # White ring, then black ring, then the state colour on top — visible
    # against a light OR a dark menu bar regardless of which one it is.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("white"))
    painter.drawEllipse(margin, margin, d, d)
    inset = max(1, size // 24)
    painter.setBrush(QColor("black"))
    painter.drawEllipse(margin + inset, margin + inset, d - 2 * inset, d - 2 * inset)
    inset2 = inset * 2
    painter.setBrush(QColor(color))
    painter.drawEllipse(margin + inset2, margin + inset2, d - 2 * inset2, d - 2 * inset2)

    painter.end()
    return pixmap


def _dot_icon(color: str) -> QIcon:
    # Two resolutions so Retina menu bars get a crisp icon instead of an
    # upscaled blurry one — Qt picks whichever matches the display.
    icon = QIcon()
    icon.addPixmap(_draw_dot(22, color))
    icon.addPixmap(_draw_dot(44, color))
    return icon


class TrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        super().__init__(_dot_icon(STATE_COLOR[SessionState.IDLE]), parent)
        self.setToolTip(f"BH-AI — {STATE_LABEL[SessionState.IDLE]}")
        menu = QMenu()
        self.show_action = menu.addAction("Show dashboard")
        self.inspector_action = menu.addAction("Trust inspector — see what the AI sees")
        self.regions_action = menu.addAction("What can the AI watch?…")
        self.quit_action = menu.addAction("Quit")
        self.setContextMenu(menu)

    def set_state(self, state: SessionState) -> None:
        self.setIcon(_dot_icon(STATE_COLOR[state]))
        self.setToolTip(f"BH-AI — {STATE_LABEL[state]}")
