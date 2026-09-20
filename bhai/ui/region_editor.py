"""
Watch-area editor — "select the area the AI CAN watch", an allowlist,
not a denylist (see `bhai/capture/watch_regions.py` for why). Roadmap
§2.4's "blocked-region editor: drag rectangles over a live screen
preview" deliverable, with the selection sense inverted.

The canvas is drawn at the SAME pixel size as its pixmap (`setFixedSize`)
specifically so coordinate math never has to reason about a scale factor
between "where you clicked" and "what's on screen" — clicks convert
straight to normalized [0,1] fractions of the canvas, which is correct
regardless of whether the preview itself is a scaled-down view of a
higher-resolution real screenshot (normalized coordinates are exactly
what makes that safe).

The preview darkens everything OUTSIDE the saved watch areas — a live
rendering of exactly what capture will actually see, not just a
decoration. With nothing selected, the whole preview is dark, matching
what a real session would capture: nothing at all.

Regions are saved via `RegionStore` the moment you release the drag —
there is no separate "Save" step, because a region you drew but forgot
to save is a privacy bug waiting to happen.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from bhai.capture.region_store import RegionStore
from bhai.capture.watch_regions import WatchRegion
from bhai.platform.portable.capture_mss import MssCaptureSource
from bhai.ui import theme

_MAX_PREVIEW_SIZE = (520, 340)
_MIN_DRAG_PX = 4  # ignore accidental clicks/tiny drags
_VEIL_ALPHA = 170  # how dark the "hidden" area looks — opaque enough to read as "gone"


def canvas_rect_to_normalized(
    rect_px: tuple[float, float, float, float], canvas_size: tuple[int, int]
) -> WatchRegion:
    """`rect_px`: (x1, y1, x2, y2) in the canvas's own pixel space, any
    corner order. Clamps to the canvas bounds and normalizes to [0, 1] —
    safe to call with drag coordinates in either direction."""
    x1, y1, x2, y2 = rect_px
    cw, ch = canvas_size
    x1, x2 = sorted((max(0.0, min(cw, x1)), max(0.0, min(cw, x2))))
    y1, y2 = sorted((max(0.0, min(ch, y1)), max(0.0, min(ch, y2))))
    return WatchRegion(x=x1 / cw, y=y1 / ch, w=(x2 - x1) / cw, h=(y2 - y1) / ch)


class RegionCanvas(QWidget):
    """Shows a screenshot, dimmed everywhere except the saved watch
    areas; drag on it to mark a new area watchable."""

    region_drawn = Signal(object)  # emits a WatchRegion

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._saved_regions: list[WatchRegion] = []
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self.setMinimumSize(*_MAX_PREVIEW_SIZE)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.setFixedSize(pixmap.size())  # 1:1 — see module docstring
        self.update()

    def set_saved_regions(self, regions: list[WatchRegion]) -> None:
        self._saved_regions = regions
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._pixmap is None:
            painter.end()
            return

        w, h = self.width(), self.height()

        # Everything starts dark — this IS what capture will actually
        # see with nothing selected, not just a UI decoration.
        painter.drawPixmap(0, 0, self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, _VEIL_ALPHA))

        # Punch the real pixels back in for each saved watch area.
        for r in self._saved_regions:
            rx, ry, rw, rh = int(r.x * w), int(r.y * h), int(r.w * w), int(r.h * h)
            painter.drawPixmap(rx, ry, self._pixmap, rx, ry, rw, rh)
            painter.setPen(QPen(QColor(theme.C["success"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rx, ry, rw, rh)

        if self._drag_start is not None and self._drag_current is not None:
            rect = QRect(self._drag_start, self._drag_current).normalized()
            painter.drawPixmap(rect, self._pixmap, rect)  # preview what this drag would reveal
            painter.setPen(QPen(QColor(theme.C["warning"]), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_current = self._drag_start

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        start, current = self._drag_start, self._drag_current
        self._drag_start = None
        self._drag_current = None
        self.update()
        if start is None or current is None:
            return
        rect = QRect(start, current).normalized()
        if rect.width() < _MIN_DRAG_PX or rect.height() < _MIN_DRAG_PX:
            return  # too small to be a deliberate drag
        region = canvas_rect_to_normalized(
            (rect.left(), rect.top(), rect.right(), rect.bottom()), (self.width(), self.height())
        )
        self.region_drawn.emit(region)


class RegionEditorWindow(QWidget):
    def __init__(self, region_store: RegionStore, parent: QWidget | None = None):
        super().__init__(parent)
        self._region_store = region_store
        self._signature: str | None = None

        self.setWindowTitle("BH-AI — What can the AI watch?")
        self.resize(560, 480)
        self.setStyleSheet(theme.window_style())

        layout = QVBoxLayout(self)

        info = QLabel(
            "Drag on the preview to allow the AI to see that area — saved "
            "immediately. Everything outside your selections stays hidden, "
            "and with nothing selected the AI sees nothing at all."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {theme.C['muted']};")
        layout.addWidget(info)

        self._canvas = RegionCanvas()
        self._canvas.region_drawn.connect(self._on_region_drawn)
        layout.addWidget(self._canvas)

        self._signature_label = QLabel("—")
        self._signature_label.setStyleSheet(f"color: {theme.C['muted']}; font-family: monospace;")
        layout.addWidget(self._signature_label)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh preview")
        refresh_btn.setStyleSheet(theme.button_style(theme.C["accent"]))
        refresh_btn.clicked.connect(self.refresh_preview)
        btn_row.addWidget(refresh_btn)

        clear_btn = QPushButton("Hide everything again")
        clear_btn.setStyleSheet(theme.button_style(theme.C["danger"]))
        clear_btn.clicked.connect(self._clear_regions)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self.refresh_preview()

    def refresh_preview(self) -> None:
        source = MssCaptureSource()
        try:
            frame = source.grab("1")
        except Exception as exc:  # noqa: BLE001 — surface it in the UI, not just stderr
            self._show_capture_problem(f"Could not capture a preview: {exc}")
            return
        finally:
            source.close()

        # macOS in particular can hand back an all-black frame with NO
        # exception at all when Screen Recording permission hasn't been
        # granted to whatever process is running this app — which would
        # otherwise look identical to "nothing selected yet" and be
        # genuinely confusing to debug from the UI alone.
        if max(frame.rgb) < 8:
            self._show_capture_problem(
                "The preview came back almost entirely black. This usually means "
                "Screen Recording permission hasn't been granted to whatever app "
                "is running BH-AI (Terminal/iTerm/your IDE). On macOS: System "
                "Settings → Privacy & Security → Screen Recording → enable it "
                "there, then click 'Refresh preview' again."
            )
            return

        self._signature = RegionStore.signature(frame.width, frame.height)
        self._signature_label.setStyleSheet(f"color: {theme.C['muted']}; font-family: monospace;")
        self._signature_label.setText(
            f"monitor 1 · {frame.width}x{frame.height} · "
            f"selections apply only to this exact resolution"
        )

        image = QImage(
            frame.rgb, frame.width, frame.height, frame.width * 3, QImage.Format.Format_RGB888
        )
        pixmap = QPixmap.fromImage(image)
        max_w, max_h = _MAX_PREVIEW_SIZE
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(
                max_w,
                max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._canvas.set_pixmap(pixmap)
        self._canvas.set_saved_regions(self._region_store.list_for(self._signature))

    def _show_capture_problem(self, message: str) -> None:
        """Make a capture failure impossible to mistake for 'nothing
        selected yet' — loud, red, and actionable, per PROJECT_CONTEXT's
        'calibrated refusal is a feature' / 'never fail silently'."""
        self._signature_label.setStyleSheet(
            f"color: {theme.C['danger']}; font-weight: 600;"
        )
        self._signature_label.setText(message)
        self._signature_label.setWordWrap(True)

    def _on_region_drawn(self, region: WatchRegion) -> None:
        if self._signature is None:
            return
        self._region_store.add(self._signature, region)
        self._canvas.set_saved_regions(self._region_store.list_for(self._signature))

    def _clear_regions(self) -> None:
        if self._signature is None:
            return
        self._region_store.clear(self._signature)
        self._canvas.set_saved_regions([])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        super().closeEvent(event)
