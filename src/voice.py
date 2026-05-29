"""
Voice Feedback Module
Text-to-speech using pyttsx3 in a background thread.
"""

import threading
import queue

try:
    import pyttsx3
    _TTS_AVAILABLE = True
except ImportError:
    _TTS_AVAILABLE = False


class VoiceFeedback:
    """
    Non-blocking TTS engine.  Queues messages and speaks them on a
    dedicated daemon thread to avoid blocking the UI.
    """

    def __init__(self, rate: int = 160, volume: float = 1.0):
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._enabled = True
        self._rate = rate
        self._volume = volume
        self._thread: threading.Thread | None = None

        if _TTS_AVAILABLE:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    @property
    def available(self) -> bool:
        return _TTS_AVAILABLE

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def speak(self, text: str):
        """Enqueue a message to be spoken (non-blocking)."""
        if self._enabled and _TTS_AVAILABLE and text:
            # Drain old queued messages to keep feedback current
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(text)

    def stop(self):
        """Cleanly stop the TTS worker."""
        if _TTS_AVAILABLE:
            self._queue.put(None)   # sentinel

    # ------------------------------------------------------------------ #
    #  Worker thread
    # ------------------------------------------------------------------ #

    def _worker(self):
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
                print(f"[Voice] TTS error: {exc}")
