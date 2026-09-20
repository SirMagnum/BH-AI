"""
Trust inspector — "See what the AI sees" (roadmap §2.4 Phase 2
deliverable, and per PROJECT_CONTEXT §8: "privacy is observable, not
documented").

Renders the EXACT redacted frame and metadata the rest of the system
would consume — nothing more, nothing prettier. This window is
deliberately the least polished thing in the app: its entire job is to
be trustworthy, not attractive. It reads frames the same way any other
consumer would — attach to the shared-memory ring by name, read the slot
the descriptor names — so what it shows is not a special privileged
view, it's what any downstream component actually sees.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bhai.bus.bus import EventBus
from bhai.bus.events import BusEvent, CaptureFrameAvailable
from bhai.bus.qt_bridge import QtEventBridge
from bhai.capture.ring import FrameRing
from bhai.ui import theme


class InspectorWindow(QWidget):
    def __init__(self, bus: EventBus, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("BH-AI — Trust Inspector: what the AI sees")
        self.resize(480, 440)
        self.setStyleSheet(theme.window_style())

        layout = QVBoxLayout(self)

        self._image_label = QLabel("No frame yet — start a session.")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            f"background-color: {theme.C['panel']}; color: {theme.C['muted']}; "
            f"border: 1px solid {theme.C['border']};"
        )
        self._image_label.setMinimumSize(400, 320)
        layout.addWidget(self._image_label)

        self._meta_label = QLabel("—")
        self._meta_label.setStyleSheet(f"color: {theme.C['muted']}; font-family: monospace;")
        layout.addWidget(self._meta_label)

        # Cache attached rings by shm_name — attaching is not free, and
        # we'll see the same ring repeatedly for as long as the session
        # (and its monitor resolution) stays unchanged.
        self._rings: dict[str, FrameRing] = {}

        self._bridge = QtEventBridge(bus, topic="capture.frame")
        self._bridge.event_received.connect(self._on_frame)
        self._bridge.start()

    def _on_frame(self, event: BusEvent) -> None:
        if not isinstance(event, CaptureFrameAvailable):
            return

        ring = self._rings.get(event.shm_name)
        if ring is None:
            ring = FrameRing(event.width, event.height, name=event.shm_name, create=False)
            self._rings[event.shm_name] = ring

        try:
            rgb = ring.read(event.slot)
        except Exception:
            # The ring can be unlinked mid-read on a pause/end race
            # (capture worker exits, we're still draining its last
            # descriptors) — skip this one frame rather than crash the
            # inspector over a normal shutdown race.
            return

        image = QImage(rgb, event.width, event.height, event.width * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(image).scaled(
            self._image_label.width(),
            self._image_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(pixmap)
        self._meta_label.setText(
            f"monitor={event.monitor_id}  {event.width}x{event.height}  "
            f"change_score={event.change_score:.3f}  ts={event.frame_ts:.2f}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._bridge.stop()
        for ring in self._rings.values():
            ring.close()
        self._rings.clear()
        super().closeEvent(event)
