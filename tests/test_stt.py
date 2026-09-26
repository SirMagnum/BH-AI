"""
Unit tests for Speech-To-Text (STT) and Voice Pipeline package.
"""

import io
import os
import tempfile
import unittest
import wave

from src.voice import (
    VoiceFeedback,
    SpeechToTextEngine,
    STTBackend,
    TranscriptionResult,
)


class TestVoiceSTT(unittest.TestCase):

    def test_voice_feedback_backward_compatibility(self):
        tts = VoiceFeedback()
        self.assertIsInstance(tts.available, bool)
        tts.set_enabled(False)
        tts.speak("Test speech")
        tts.stop()

    def test_stt_mock_backend(self):
        stt = SpeechToTextEngine(backend=STTBackend.MOCK)
        self.assertEqual(stt.backend_name, STTBackend.MOCK.value)
        self.assertFalse(stt.available)

    def test_stt_transcribe_pcm_and_wav(self):
        stt = SpeechToTextEngine(backend=STTBackend.MOCK)

        # Generate 0.5s of synthetic 16kHz 16-bit mono PCM audio
        sample_rate = 16000
        num_samples = int(sample_rate * 0.5)
        raw_pcm = b"\x00\x01" * num_samples

        res = stt.transcribe_pcm(raw_pcm, sample_rate=sample_rate)
        self.assertIsInstance(res, TranscriptionResult)
        self.assertGreater(len(res.text), 0)
        self.assertAlmostEqual(res.duration, 0.5, places=2)
        self.assertEqual(res.language, "en")

    def test_stt_transcribe_file(self):
        stt = SpeechToTextEngine(backend=STTBackend.MOCK)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x10\x20" * 8000)

        try:
            res = stt.transcribe_file(tmp_path)
            self.assertIsInstance(res, TranscriptionResult)
            self.assertGreater(len(res.text), 0)
            self.assertGreater(res.confidence, 0.0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_stt_empty_and_missing_files(self):
        stt = SpeechToTextEngine(backend=STTBackend.MOCK)
        res_empty = stt.transcribe_pcm(b"")
        self.assertEqual(res_empty.text, "")

        res_missing = stt.transcribe_file("non_existent_file_123.wav")
        self.assertEqual(res_missing.text, "")


if __name__ == "__main__":
    unittest.main()
