"""
Floating pill HUD — migrated from the prototype's `src/ui_user.py`.

This is what a user runs; DashboardWindow is what the team debugs with.
Both read the same event bus, per roadmap Phase 1's prototype-migration
note: the dual-mode split is a genuinely good product decision the v1.0
plan didn't have, and it's adopted rather than discarded.

Dropped for now: the prototype's window picker (`_enum_windows`, built on
the Win32 user32 EnumWindows call) — that's Windows-only and belongs
behind a platform interface once Phase 3 needs "which window is
foreground" cross-platform. Rebuilding it prematurely here would just be
more code to migrate twice.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from bhai.bus.bus import EventBus
from bhai.bus.events import BusEvent
from bhai.bus.qt_bridge import QtEventBridge
from bhai.session.manager import SessionManager
from bhai.session.states import SessionEvent, SessionState
from bhai.ui import theme

_PILL_STYLE = f"""
    QWidget#pill {{
        background-color: {theme.C["surface"]};
        border: 1px solid {theme.C["border"]};
        border-radius: 22px;
    }}
"""


class HudWindow(QWidget):
    def __init__(self, manager: SessionManager, bus: EventBus, parent: QWidget | None = None):
        super().__init__(parent)
        self._manager = manager
        self._bus = bus
        self._drag_offset: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("pill")
        self.setStyleSheet(_PILL_STYLE)
        self.setFixedSize(280, 56)

        self._build_ui()

        self._bridge = QtEventBridge(bus, topic="session.state_changed")
        self._bridge.event_received.connect(self._on_event)
        self._bridge.start()

        self._refresh()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {theme.STATE_COLOR[SessionState.IDLE]}; font-size: 18px;")
        layout.addWidget(self._dot)

        self._label = QLabel(theme.STATE_LABEL[SessionState.IDLE])
        self._label.setStyleSheet(f"color: {theme.C['text']}; font-weight: 600;")
        layout.addWidget(self._label, stretch=1)

        self._primary_btn = QPushButton("▶")
        self._primary_btn.setFixedSize(32, 32)
        self._primary_btn.setStyleSheet(theme.button_style(theme.C["success"]))
        self._primary_btn.clicked.connect(self._on_primary)
        layout.addWidget(self._primary_btn)

        self._end_btn = QPushButton("⏹")
        self._end_btn.setFixedSize(32, 32)
        self._end_btn.setStyleSheet(theme.button_style(theme.C["danger"]))
        self._end_btn.clicked.connect(self._on_end)
        layout.addWidget(self._end_btn)

    # ------------------------------------------------------------------ #
    #  The pill's one button does start/pause/resume depending on state —
    #  it is one control whose meaning is entirely FSM-driven, which is
    #  the same "no ad-hoc conditionals" rule as the dashboard, just
    #  expressed as one button instead of three.
    # ------------------------------------------------------------------ #

    def _on_primary(self) -> None:
        m = self._manager
        if m.can(SessionEvent.START):
            m.start()
        elif m.can(SessionEvent.PAUSE):
            m.pause()
        elif m.can(SessionEvent.RESUME):
            m.resume()
        self._refresh()

    def _on_end(self) -> None:
        if self._manager.can(SessionEvent.END):
            self._manager.end()
            # HUD stays minimal — no save/discard dialog here. Real policy
            # (default ephemeral, explicit save) is a Phase 1 UX decision
            # to finish in the dashboard for now; HUD always discards.
            self._manager.finish(save=False)
        self._refresh()

    def _refresh(self) -> None:
        m = self._manager
        state = m.state
        self._dot.setStyleSheet(f"color: {theme.STATE_COLOR[state]}; font-size: 18px;")
        self._label.setText(theme.STATE_LABEL[state])

        if m.can(SessionEvent.START):
            self._primary_btn.setText("▶")
            self._primary_btn.setStyleSheet(theme.button_style(theme.C["success"]))
        elif m.can(SessionEvent.PAUSE):
            self._primary_btn.setText("⏸")
            self._primary_btn.setStyleSheet(theme.button_style(theme.C["warning"]))
        elif m.can(SessionEvent.RESUME):
            self._primary_btn.setText("▶")
            self._primary_btn.setStyleSheet(theme.button_style(theme.C["accent"]))
        else:
            self._primary_btn.setEnabled(False)

        self._end_btn.setEnabled(m.can(SessionEvent.END))

    def _on_event(self, _event: BusEvent) -> None:
        self._refresh()

    # ------------------------------------------------------------------ #
    #  Draggable — ported from the prototype's `_make_draggable`.
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._bridge.stop()
        super().closeEvent(event)
