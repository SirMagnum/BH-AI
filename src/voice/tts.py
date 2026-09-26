"""
Voice Feedback / Text-To-Speech Module for BH-AI.
Uses pyttsx3 in a non-blocking background thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

logger = logging.getLogger("BH-AI.TTS")

_TTS_AVAILABLE = False
try:
    import pyttsx3
    _TTS_AVAILABLE = True
except ImportError:
    _TTS_AVAILABLE = False


class VoiceFeedback:
    """
    Non-blocking TTS engine. Queues messages and speaks them on a
    dedicated daemon thread to avoid blocking the UI or main thread.
    """

    def __init__(self, rate: int = 160, volume: float = 1.0):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._enabled = True
        self._rate = rate
        self._volume = volume
        self._thread: threading.Thread | None = None

        if _TTS_AVAILABLE:
            self._thread = threading.Thread(target=self._worker, daemon=True, name="TTSWorker")
            self._thread.start()

    @property
    def available(self) -> bool:
        return _TTS_AVAILABLE

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def speak(self, text: str) -> None:
        """Enqueue a message to be spoken (non-blocking)."""
        if self._enabled and _TTS_AVAILABLE and text:
            # Drain older queued messages to keep spoken feedback fresh
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(text)

    def stop(self) -> None:
        """Cleanly stop the TTS worker."""
        if _TTS_AVAILABLE:
            self._queue.put(None)

    def _worker(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            engine.setProperty("volume", self._volume)

            while True:
                text = self._queue.get()
                if text is None:
                    break
                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception as exc:
                    logger.error(f"[Voice] TTS error: {exc}")
        except Exception as exc:
            logger.error(f"[Voice] Failed to initialize pyttsx3 engine: {exc}")
