"""
BH-AI Voice Pipeline Package.
Provides Text-To-Speech (TTS), Offline Speech-To-Text (STT), and Wake-Word / Push-To-Talk spotting.
"""

from src.voice.tts import VoiceFeedback
from src.voice.stt import (
    SpeechToTextEngine,
    STTBackend,
    TranscriptionResult,
)
from src.voice.wakeword import (
    WakeWordDetector,
    PushToTalkManager,
    VoiceTriggerController,
)

__all__ = [
    "VoiceFeedback",
    "SpeechToTextEngine",
    "STTBackend",
    "TranscriptionResult",
    "WakeWordDetector",
    "PushToTalkManager",
    "VoiceTriggerController",
]
