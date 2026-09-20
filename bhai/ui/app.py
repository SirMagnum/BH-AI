"""
App bootstrap: wires EventBus, SessionStore, SessionManager, and the three
UI surfaces (dashboard, HUD, tray) together on a qasync event loop.

This is the only module that constructs all three UI surfaces — everyone
else only ever sees a SessionManager + EventBus passed in, which is what
keeps main_window.py / hud.py / tray.py independently testable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import qasync
from PySide6.QtWidgets import QApplication

from bhai.bus.bus import EventBus
from bhai.bus.events import SessionStateChanged
from bhai.bus.qt_bridge import QtEventBridge
from bhai.capture.region_store import RegionStore
from bhai.db.store import SessionStore
from bhai.logging_setup import configure_logging
from bhai.session.manager import SessionManager
from bhai.ui.hud import HudWindow
from bhai.ui.inspector import InspectorWindow
from bhai.ui.main_window import DashboardWindow
from bhai.ui.region_editor import RegionEditorWindow
from bhai.ui.tray import TrayIcon


def _data_dir() -> Path:
    """Per-user data directory for the session DB.

    Minimal on purpose: proper per-OS resolution (AppData / Application
    Support / XDG) is a Phase 10 packaging concern. `~/.bhai` is fine for
    development and is exactly why `.venv`-adjacent runtime data belongs
    in `.gitignore`, not in the repo.
    """
    base = Path.home() / ".bhai"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main() -> int:
    configure_logging()

    app = QApplication(sys.argv)
    # Closing the dashboard window must not kill the tray/HUD — the app
    # only exits via explicit Quit, matching "pause ≠ exit" expectations.
    app.setQuitOnLastWindowClosed(False)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    bus = EventBus()
    db_path = _data_dir() / "sessions.db"
    store = SessionStore(db_path)
    # same file, WAL-shared; regions are global, not session-scoped
    region_store = RegionStore(db_path)
    manager = SessionManager(bus, store, region_store=region_store)

    # Constructed before the dashboard so their show()/raise_ callbacks
    # can be wired straight into it — the dashboard is the primary way
    # to reach these now, not the tray (see main_window.py's comment on
    # why: a menu-bar icon is too easy to miss).
    inspector = InspectorWindow(bus)
    region_editor = RegionEditorWindow(region_store)

    def _open_inspector() -> None:
        inspector.show()
        inspector.raise_()

    def _open_region_editor() -> None:
        region_editor.refresh_preview()
        region_editor.show()
        region_editor.raise_()

    dashboard = DashboardWindow(
        manager, bus, open_inspector=_open_inspector, open_region_editor=_open_region_editor
    )
    hud = HudWindow(manager, bus)
    tray = TrayIcon()

    tray.show_action.triggered.connect(dashboard.show)
    tray.show_action.triggered.connect(dashboard.raise_)
    tray.inspector_action.triggered.connect(inspector.show)
    tray.inspector_action.triggered.connect(inspector.raise_)
    tray.regions_action.triggered.connect(region_editor.refresh_preview)
    tray.regions_action.triggered.connect(region_editor.show)
    tray.regions_action.triggered.connect(region_editor.raise_)
    tray.quit_action.triggered.connect(app.quit)

    tray_bridge = QtEventBridge(bus, topic="session.state_changed")

    def _on_tray_state_event(event: object) -> None:
        if isinstance(event, SessionStateChanged):
            tray.set_state(event.new_state)

    tray_bridge.event_received.connect(_on_tray_state_event)
    tray_bridge.start()

    def _shutdown() -> None:
        # Guarantees no orphaned capture process on quit, regardless of
        # what state the session was in — the last line of defence for
        # invariant 1, alongside daemon=True on the worker process itself.
        manager.shutdown()
        store.close()
        region_store.close()

    app.aboutToQuit.connect(_shutdown)

    dashboard.show()
    hud.show()
    tray.show()

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    sys.exit(main())
