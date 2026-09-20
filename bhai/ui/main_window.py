"""
Dev dashboard — migrated from the prototype's `src/ui.py`.

Buttons are enabled/disabled by `SessionManager.can(event)`, never by
ad-hoc conditionals — the roadmap's Phase 1 frontend responsibility is
"state-machine-driven UI". The event log panel subscribes to every bus
event via `QtEventBridge` and is kept permanently, per the roadmap: "the
live event log developer panel... keep this permanently; it's invaluable."

What did NOT survive the migration: `src/analyzer.py`'s keyword rules
(superseded by the LLM in Phase 5) and the tkinter windowing (superseded
by Qt — see roadmap §1, "Why the Tauri + Rust stack was dropped").
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bhai.bus.bus import EventBus
from bhai.bus.events import BusEvent
from bhai.bus.qt_bridge import QtEventBridge
from bhai.session.manager import SessionManager
from bhai.session.states import SessionEvent, SessionState
from bhai.ui import theme


class DashboardWindow(QWidget):
    def __init__(
        self,
        manager: SessionManager,
        bus: EventBus,
        parent: QWidget | None = None,
        open_inspector: Callable[[], None] | None = None,
        open_region_editor: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._bus = bus
        self._open_inspector = open_inspector
        self._open_region_editor = open_region_editor

        self.setWindowTitle("BH-AI — Dev Dashboard")
        self.resize(560, 420)
        self.setStyleSheet(theme.window_style())

        self._build_ui()

        self._bridge = QtEventBridge(bus)  # None topic: every event, for the log panel
        self._bridge.event_received.connect(self._on_event)
        self._bridge.start()

        self._refresh()

    # ------------------------------------------------------------------ #
    #  Layout
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._state_label = QLabel(theme.STATE_LABEL[SessionState.IDLE])
        self._state_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {theme.C['accent']};"
        )
        layout.addWidget(self._state_label)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶  Start")
        self._pause_btn = QPushButton("⏸  Pause")
        self._resume_btn = QPushButton("▶  Resume")
        self._end_btn = QPushButton("⏹  End")
        for btn, color in (
            (self._start_btn, theme.C["success"]),
            (self._pause_btn, theme.C["warning"]),
            (self._resume_btn, theme.C["accent"]),
            (self._end_btn, theme.C["danger"]),
        ):
            btn.setStyleSheet(theme.button_style(color))
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn.clicked.connect(self._on_pause)
        self._resume_btn.clicked.connect(self._on_resume)
        self._end_btn.clicked.connect(self._on_end)

        self._pid_label = QLabel("capture pid: —")
        self._pid_label.setStyleSheet(f"color: {theme.C['muted']};")
        layout.addWidget(self._pid_label)

        # Direct buttons for the tray-only tools — a tiny menu-bar dot is
        # too easy to miss (and its idle colour is low-contrast against
        # both light and dark menu bars), so these are the primary way
        # in, not a backup.
        tools_row = QHBoxLayout()
        inspector_btn = QPushButton("🔍  Trust inspector")
        inspector_btn.setStyleSheet(theme.button_style(theme.C["accent"]))
        inspector_btn.clicked.connect(self._on_open_inspector)
        tools_row.addWidget(inspector_btn)

        regions_btn = QPushButton("👁  What can the AI watch?")
        regions_btn.setStyleSheet(theme.button_style(theme.C["accent"]))
        regions_btn.clicked.connect(self._on_open_region_editor)
        tools_row.addWidget(regions_btn)
        layout.addLayout(tools_row)

        log_header = QLabel("Event log")
        log_header.setStyleSheet(f"color: {theme.C['muted']}; margin-top: 8px;")
        layout.addWidget(log_header)

        self._log_list = QListWidget()
        self._log_list.setStyleSheet(
            f"background-color: {theme.C['panel']}; color: {theme.C['text']}; "
            f"border: 1px solid {theme.C['border']};"
        )
        layout.addWidget(self._log_list)

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #

    def _on_start(self) -> None:
        self._manager.start()
        self._refresh()

    def _on_pause(self) -> None:
        self._manager.pause()
        self._refresh()

    def _on_resume(self) -> None:
        self._manager.resume()
        self._refresh()

    def _on_open_inspector(self) -> None:
        if self._open_inspector is not None:
            self._open_inspector()

    def _on_open_region_editor(self) -> None:
        if self._open_region_editor is not None:
            self._open_region_editor()

    def _on_end(self) -> None:
        self._manager.end()
        self._refresh()
        choice = QMessageBox.question(
            self,
            "Save session?",
            "Keep this session's data, or discard it?\n\n"
            "Discarding deletes every row for this session in one transaction — "
            "nothing about it is recoverable afterward.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard,
            QMessageBox.StandardButton.Discard,
        )
        self._manager.finish(save=(choice == QMessageBox.StandardButton.Save))
        self._refresh()

    # ------------------------------------------------------------------ #
    #  State sync — the rule the roadmap asks for: buttons reflect the
    #  FSM, never an ad-hoc "if running and not paused" check scattered
    #  across handlers.
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        m = self._manager
        self._start_btn.setEnabled(m.can(SessionEvent.START))
        self._pause_btn.setEnabled(m.can(SessionEvent.PAUSE))
        self._resume_btn.setEnabled(m.can(SessionEvent.RESUME))
        self._end_btn.setEnabled(m.can(SessionEvent.END))
        self._state_label.setText(theme.STATE_LABEL[m.state])
        self._state_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {theme.STATE_COLOR[m.state]};"
        )
        self._pid_label.setText(f"capture pid: {m.capture_pid or '—'}")

    def _on_event(self, event: BusEvent) -> None:
        summary = event.model_dump_json(exclude={"event_id", "ts"})
        self._log_list.addItem(QListWidgetItem(f"[{event.topic}] {summary}"))
        self._log_list.scrollToBottom()
        # Any event that could change what's legal gets a button refresh —
        # cheapest correct rule, and refresh() itself is idempotent.
        self._refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt override
        self._bridge.stop()
        super().closeEvent(event)
