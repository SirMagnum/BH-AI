"""
Screen Capture Module
Handles user-selected region capture with start/pause support.
"""

import mss
import mss.tools
from PIL import Image
import threading
import time
import io


class ScreenCapture:
    """
    Captures a user-defined screen region at a set interval.
    Thread-safe with start/pause control.
    """

    def __init__(self, region: dict | None = None, fps: float = 1.0):
        """
        :param region: dict with keys x, y, width, height (screen coords)
        :param fps: captures per second
        """
        self.region = region          # {x, y, width, height}
        self.fps = fps
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest_frame: Image.Image | None = None
        self._on_frame_callback = None  # callable(PIL.Image)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def set_region(self, x: int, y: int, width: int, height: int):
        with self._lock:
            self.region = {"left": x, "top": y, "width": width, "height": height}

    def set_callback(self, fn):
        """Register a callback that receives each captured PIL.Image frame."""
        self._on_frame_callback = fn

    def start(self):
        if self._running:
            return
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._running = False
        self._paused = False
        self._thread = None
        self._latest_frame = None

    @property
    def latest_frame(self) -> Image.Image | None:
        with self._lock:
            return self._latest_frame

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    # ------------------------------------------------------------------ #
    #  Internal capture loop
    # ------------------------------------------------------------------ #

    def _loop(self):
        interval = 1.0 / max(self.fps, 0.1)
        with mss.mss() as sct:
            while self._running:
                if self._paused or self.region is None:
                    time.sleep(0.1)
                    continue

                try:
                    with self._lock:
                        region = self.region.copy()

                    raw = sct.grab(region)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                    with self._lock:
                        self._latest_frame = img

                    if self._on_frame_callback:
                        self._on_frame_callback(img.copy())

                except Exception as exc:
                    print(f"[Capture] Error: {exc}")

                time.sleep(interval)
