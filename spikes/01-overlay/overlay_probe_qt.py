"""
Spike 1 (macOS): can PySide6 give us a transparent, always-on-top,
click-through overlay with annotation primitives — the thing tkinter
cannot do on this platform?

Verdict criteria:
  1. Frameless + translucent window                     -> can we see through it
  2. WindowTransparentForInput / WA_TransparentForMouseEvents -> click-through
  3. Always-on-top above other apps
  4. Multi-screen geometry with correct devicePixelRatio (DPI)
  5. Draws arrow/circle/label primitives (Phase 7 needs these)
"""
import sys

from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QFont, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget

RESULTS = {}


class Overlay(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.setScreen(screen)

        # (1) frameless + translucent, (3) always on top, (2) click-through
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                      # no dock icon, no focus steal
            | Qt.WindowTransparentForInput # <- click-through, the critical one
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.setGeometry(screen.geometry())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # (5) the Phase 7 annotation primitives
        pen = QPen(QColor("#00E5FF"), 4)
        p.setPen(pen)
        p.drawEllipse(QRectF(180, 180, 220, 120))          # circle a button

        p.setPen(QPen(QColor("#FFC107"), 4))
        p.drawLine(QPointF(460, 240), QPointF(640, 240))   # arrow shaft
        head = QPolygonF([QPointF(640, 240), QPointF(616, 228), QPointF(616, 252)])
        p.setBrush(QColor("#FFC107"))
        p.drawPolygon(head)                                 # arrow head

        p.setPen(QPen(QColor("#69F0AE"), 3))
        p.drawRect(QRectF(180, 360, 300, 90))              # box a field

        p.setFont(QFont("Helvetica", 16, QFont.Bold))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(190, 160, "Step 1 — click Export")      # numbered label
        p.end()


def main():
    app = QApplication(sys.argv)

    screens = QGuiApplication.screens()
    RESULTS["qt_version"] = __import__("PySide6").QtCore.__version__
    RESULTS["screens"] = [
        {
            "name": s.name(),
            "geometry": (s.geometry().x(), s.geometry().y(),
                         s.geometry().width(), s.geometry().height()),
            "devicePixelRatio": s.devicePixelRatio(),   # (4) DPI / Retina scaling
            "logicalDotsPerInch": round(s.logicalDotsPerInch(), 1),
        }
        for s in screens
    ]

    windows = []
    for s in screens:
        try:
            w = Overlay(s)
            w.show()
            windows.append(w)
        except Exception as exc:
            RESULTS.setdefault("errors", []).append(f"{s.name()}: {exc!r}")

    def verify():
        w = windows[0]
        RESULTS["frameless"] = bool(w.windowFlags() & Qt.FramelessWindowHint)
        RESULTS["always_on_top"] = bool(w.windowFlags() & Qt.WindowStaysOnTopHint)
        RESULTS["click_through_flag"] = bool(w.windowFlags() & Qt.WindowTransparentForInput)
        RESULTS["translucent_attr"] = w.testAttribute(Qt.WA_TranslucentBackground)
        RESULTS["mouse_transparent_attr"] = w.testAttribute(Qt.WA_TransparentForMouseEvents)
        RESULTS["window_is_visible"] = w.isVisible()
        RESULTS["overlay_count"] = len(windows)

        # prove it actually rendered rather than merely being "visible"
        RESULTS["grabbed_nonempty"] = not w.grab().isNull()

        app.quit()

    QTimer.singleShot(1200, verify)   # leave it on screen briefly, then check
    app.exec()

    import json
    print(json.dumps(RESULTS, indent=2))


if __name__ == "__main__":
    main()
