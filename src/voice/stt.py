"""
Local Offline Speech-to-Text (STT) Module for BH-AI.
Supports multi-backend execution:
  - faster-whisper (CTranslate2 accelerated Whisper)
  - whisper (OpenAI Whisper local package)
  - Mock backend for deterministic testing / fallback
"""

from __future__ import annotations

import enum
import io
import logging
import os
import tempfile
import threading
import wave
from dataclasses import dataclass
from typing import Any
import numpy as np

logger = logging.getLogger("BH-AI.STT")


class STTBackend(str, enum.Enum):
    AUTO = "auto"
    FASTER_WHISPER = "faster_whisper"
    WHISPER = "whisper"
    MOCK = "mock"


@dataclass(frozen=True)
class TranscriptionResult:
    """Represents a speech transcription output."""
    text: str
    language: str = "en"
    confidence: float = 1.0
    duration: float = 0.0


# ------------------------------------------------------------------ #
#  Backend Availability Discovery
# ------------------------------------------------------------------ #

_FASTER_WHISPER_AVAILABLE = False
try:
    import faster_whisper
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _FASTER_WHISPER_AVAILABLE = False

_WHISPER_AVAILABLE = False
try:
    import whisper
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False


# ------------------------------------------------------------------ #
#  Speech-To-Text Engine
# ------------------------------------------------------------------ #

class SpeechToTextEngine:
    """
    Offline Speech-to-Text transcriber with Whisper integration.
    """

    def __init__(
        self,
        model_size: str = "tiny",
        backend: STTBackend | str = STTBackend.AUTO,
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._lock = threading.RLock()

        if isinstance(backend, STTBackend):
            self._backend_pref = backend
        else:
            self._backend_pref = STTBackend(str(backend).lower())

        self._active_backend: STTBackend = self._resolve_backend()
        self._model_instance: Any = None
        self._init_backend()

    def _resolve_backend(self) -> STTBackend:
        if self._backend_pref == STTBackend.MOCK:
            return STTBackend.MOCK

        if self._backend_pref == STTBackend.FASTER_WHISPER:
            if _FASTER_WHISPER_AVAILABLE:
                return STTBackend.FASTER_WHISPER
            logger.warning("[STT] faster-whisper requested but not installed.")

        if self._backend_pref == STTBackend.WHISPER:
            if _WHISPER_AVAILABLE:
                return STTBackend.WHISPER
            logger.warning("[STT] whisper requested but not installed.")

        # AUTO selection
        if _FASTER_WHISPER_AVAILABLE:
            return STTBackend.FASTER_WHISPER
        if _WHISPER_AVAILABLE:
            return STTBackend.WHISPER

        return STTBackend.MOCK

    def _init_backend(self) -> None:
        """Instantiate selected model."""
        with self._lock:
            if self._active_backend == STTBackend.FASTER_WHISPER:
                try:
                    from faster_whisper import WhisperModel
                    self._model_instance = WhisperModel(
                        self.model_size, device=self.device, compute_type=self.compute_type
                    )
                except Exception as exc:
                    logger.error(f"[STT] Failed to load faster-whisper: {exc}")
                    self._active_backend = STTBackend.MOCK

            elif self._active_backend == STTBackend.WHISPER:
                try:
                    import whisper
                    self._model_instance = whisper.load_model(self.model_size, device=self.device)
                except Exception as exc:
                    logger.error(f"[STT] Failed to load whisper: {exc}")
                    self._active_backend = STTBackend.MOCK

    @property
    def available(self) -> bool:
        """True if a real neural STT model (faster-whisper or whisper) is loaded."""
        return self._active_backend in (STTBackend.FASTER_WHISPER, STTBackend.WHISPER)

    @property
    def backend_name(self) -> str:
        return self._active_backend.value

    # ------------------------------------------------------------------ #
    #  Transcription APIs
    # ------------------------------------------------------------------ #

    def transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """Transcribe an audio file from disk."""
        if not os.path.isfile(audio_path):
            return TranscriptionResult(text="", confidence=0.0)

        with self._lock:
            if self._active_backend == STTBackend.FASTER_WHISPER:
                segments, info = self._model_instance.transcribe(audio_path, beam_size=1)
                text = " ".join(seg.text for seg in segments).strip()
                return TranscriptionResult(
                    text=text,
                    language=info.language,
                    confidence=float(info.language_probability),
                    duration=float(info.duration),
                )

            elif self._active_backend == STTBackend.WHISPER:
                res = self._model_instance.transcribe(audio_path)
                return TranscriptionResult(
                    text=res.get("text", "").strip(),
                    language=res.get("language", "en"),
                    confidence=1.0,
                )

            else:  # MOCK
                return self._mock_transcribe_file(audio_path)

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        sample_width: int = 2,
        channels: int = 1,
    ) -> TranscriptionResult:
        """
        Transcribe raw PCM audio bytes.
        Writes to an in-memory WAV buffer and processes through the active model.
        """
        if not pcm_bytes:
            return TranscriptionResult(text="", confidence=0.0)

        duration = len(pcm_bytes) / (sample_rate * sample_width * channels)

        # Build WAV in memory
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        wav_buf.seek(0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_buf.read())
            tmp_path = tmp.name

        try:
            res = self.transcribe_file(tmp_path)
            return TranscriptionResult(
                text=res.text,
                language=res.language,
                confidence=res.confidence,
                duration=duration,
            )
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def _mock_transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """Mock transcription reading file metadata."""
        size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
        if size > 44:  # Non-empty WAV
            return TranscriptionResult(
                text="Hello assistant, show me my recent activity.",
                language="en",
                confidence=0.98,
                duration=round(size / 32000.0, 2),
            )
        return TranscriptionResult(text="", confidence=0.0, duration=0.0)
