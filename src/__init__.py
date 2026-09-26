# Privacy Assistant - src package
from src.state_machine import StateMachine, State, Trigger, InvalidStateTransitionError
from src.ocr import OCRProcessor, OCRBox, OCRBackend
from src.reasoning import LocalLLMDriver, LLMBackend, LLMConfig, LLMResponse
from src.overlay import OverlayWindow, OverlayRect
from src.benchmark import SystemBenchmark, BenchmarkReport

__all__ = [
    "StateMachine",
    "State",
    "Trigger",
    "InvalidStateTransitionError",
    "OCRProcessor",
    "OCRBox",
    "OCRBackend",
    "LocalLLMDriver",
    "LLMBackend",
    "LLMConfig",
    "LLMResponse",
    "OverlayWindow",
    "OverlayRect",
    "SystemBenchmark",
    "BenchmarkReport",
]

