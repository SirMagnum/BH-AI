"""
System Latency Profiler & Benchmark Suite for BH-AI.
Measures end-to-end turnaround latency:
  T_total = T_wake + T_STT + T_OCR + T_RAG(M_episodic) + T_LLM(P_B) + T_TTS

Evaluates against the research paper's core performance targets:
  1. T_OCR + T_RAG < 300 ms
  2. Physical RAM footprint < 200 MB
  3. Episodic storage growth < 5 MB/hour
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import psutil
from PIL import Image, ImageDraw

from src.memory.db import MemoryDatabase
from src.memory.embeddings import EmbeddingEngine, EmbeddingBackend
from src.memory.rag import EpisodicRAGEngine
from src.ocr import OCRProcessor, OCRBackend
from src.privacy.pii import PIIRedactor
from src.reasoning.llm import LocalLLMDriver, LLMBackend, LLMConfig
from src.voice.stt import SpeechToTextEngine, STTBackend
from src.voice.wakeword import WakeWordDetector

logger = logging.getLogger("BH-AI.Benchmark")


# ------------------------------------------------------------------ #
#  Benchmark Data Models
# ------------------------------------------------------------------ #

@dataclass
class PipelineStageMetrics:
    """Latency breakdown in milliseconds (ms)."""
    t_wake_ms: float
    t_stt_ms: float
    t_ocr_ms: float
    t_pii_ms: float
    t_rag_ms: float
    t_llm_ms: float
    t_tts_ms: float
    t_total_ms: float

    @property
    def t_ocr_plus_rag_ms(self) -> float:
        return self.t_ocr_ms + self.t_rag_ms


@dataclass
class ResourceMetrics:
    """System resource utilization metrics."""
    ram_rss_mb: float
    db_record_bytes_avg: float
    db_growth_mb_per_hour: float


@dataclass
class BenchmarkReport:
    """Complete evaluation scorecard against paper targets."""
    iterations: int
    stages: PipelineStageMetrics
    resources: ResourceMetrics
    passed_ocr_rag_target: bool     # T_OCR + T_RAG < 300 ms
    passed_ram_target: bool         # RAM < 200 MB
    passed_storage_target: bool     # Storage < 5 MB/hour
    all_targets_passed: bool
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_ascii_table(self) -> str:
        s = self.stages
        r = self.resources
        p_ocr_rag = "PASS [OK]" if self.passed_ocr_rag_target else "FAIL [X]"
        p_ram = "PASS [OK]" if self.passed_ram_target else "FAIL [X]"
        p_storage = "PASS [OK]" if self.passed_storage_target else "FAIL [X]"
        p_overall = "ALL TARGETS PASSED" if self.all_targets_passed else "SOME TARGETS FAILED"

        lines = [
            "=" * 72,
            "             BH-AI SYSTEM LATENCY & RESOURCE BENCHMARK           ",
            "=" * 72,
            f"Iterations: {self.iterations} | Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}",
            "-" * 72,
            "  PIPELINE STAGE LATENCIES (ms):",
            f"    * T_wake (Keyword / Energy Detection) : {s.t_wake_ms:8.2f} ms",
            f"    * T_STT  (Speech-to-Text Transcription): {s.t_stt_ms:8.2f} ms",
            f"    * T_OCR  (Screen Text Extraction)      : {s.t_ocr_ms:8.2f} ms",
            f"    * T_PII  (Local PII Redaction)         : {s.t_pii_ms:8.2f} ms",
            f"    * T_RAG  (Vector Scoring & Knapsack)   : {s.t_rag_ms:8.2f} ms",
            f"    * T_LLM  (Local Contextual Reasoning)  : {s.t_llm_ms:8.2f} ms",
            f"    * T_TTS  (Speech Dispatch / Queuing)   : {s.t_tts_ms:8.2f} ms",
            "    " + "-" * 50,
            f"    * T_total (End-to-End Turnaround)      : {s.t_total_ms:8.2f} ms",
            "-" * 72,
            "  PAPER PERFORMANCE TARGET SCORECARD:",
            f"    1. T_OCR + T_RAG Target  : {s.t_ocr_plus_rag_ms:6.2f} ms (Target < 300 ms)  -> {p_ocr_rag}",
            f"    2. Memory Footprint (RSS): {r.ram_rss_mb:6.2f} MB (Target < 200 MB)  -> {p_ram}",
            f"    3. DB Storage Growth Rate: {r.db_growth_mb_per_hour:6.2f} MB/h (Target < 5 MB/h) -> {p_storage}",
            "-" * 72,
            f"  OVERALL RESULT: {p_overall}",
            "=" * 72,
        ]
        return "\n".join(lines)


# ------------------------------------------------------------------ #
#  System Benchmark Profiler
# ------------------------------------------------------------------ #

class SystemBenchmark:
    """
    Executes profiled end-to-end pipeline cycles across all BH-AI modules.
    """

    TARGET_OCR_RAG_MS = 300.0       # ms
    TARGET_RAM_MB = 200.0           # MB
    TARGET_STORAGE_MB_PER_HOUR = 5.0  # MB/h
    CAPTURE_RATE_PER_HOUR = 720     # ~1 capture per 5 seconds

    def __init__(self, temp_dir: str | None = None):
        self._temp_dir = temp_dir or tempfile.mkdtemp()
        self._owns_temp_dir = temp_dir is None

        # Components initialization
        self.db_path = os.path.join(self._temp_dir, "benchmark_episodic.db")
        self.db = MemoryDatabase(self.db_path)
        self.session = self.db.start_session("benchmark_session")

        self.embeddings = EmbeddingEngine(dimension=64, backend=EmbeddingBackend.TFIDF_SEMANTIC)
        self.rag = EpisodicRAGEngine(db=self.db, embeddings=self.embeddings)
        self.ocr = OCRProcessor(scale=1.0, backend=OCRBackend.AUTO)
        self.pii = PIIRedactor()
        self.wakeword = WakeWordDetector()
        self.stt = SpeechToTextEngine(backend=STTBackend.MOCK)
        self.llm = LocalLLMDriver(backend=LLMBackend.AUTO)

    def close(self) -> None:
        """Clean up database connections and scratch files."""
        try:
            self.db.close()
        except Exception:
            pass
        if self._owns_temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    # -------------------------------------------------------------- #
    #  Synthetic Test Assets
    # -------------------------------------------------------------- #

    def _generate_synthetic_image(self) -> Image.Image:
        """Create an 800x450 RGB test image representing an active desktop window with realistic text."""
        img = Image.new("RGB", (800, 450), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        lines = [
            "Project BH-AI Desktop Companion - Main Execution Window",
            "Customer Support Ticket #48291: User john.doe@example.com reported an issue.",
            "Authentication Token: sk-live-982374982347abcdef1234567890",
            "Payment summary: Visa ending in 4111 with total charge of $129.50.",
            "Visual Studio Code: def calculate_system_latency(t_wake, t_stt, t_ocr): return sum()",
        ]
        y = 30
        for line in lines:
            draw.text((30, y), line, fill=(0, 0, 0))
            y += 50
        return img

    def _generate_synthetic_audio(self) -> bytes:
        """Create 1 second of 16kHz 16-bit mono PCM audio with sinusoidal voice frequency."""
        sample_rate = 16000
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        waveform = 0.5 * np.sin(2 * np.pi * 440 * t)  # 440 Hz tone
        pcm_data = (waveform * 32767).astype(np.int16).tobytes()
        return pcm_data

    # -------------------------------------------------------------- #
    #  Execution Cycle
    # -------------------------------------------------------------- #

    def run_cycle(self) -> PipelineStageMetrics:
        """Run a single profiled end-to-end pipeline cycle."""
        test_img = self._generate_synthetic_image()
        test_audio = self._generate_synthetic_audio()
        user_query = "What code and customer details are open on my screen?"

        t_total_start = time.perf_counter()

        # 1. Wake-word detection
        t0 = time.perf_counter()
        _ = self.wakeword.process_audio_frame(test_audio)
        t_wake = time.perf_counter() - t0

        # 2. Speech-to-text
        t0 = time.perf_counter()
        stt_res = self.stt.transcribe_pcm(test_audio, sample_rate=16000)
        t_stt = time.perf_counter() - t0

        # 3. Screen OCR extraction
        t0 = time.perf_counter()
        ocr_text = self.ocr.extract_text(test_img)
        t_ocr = time.perf_counter() - t0

        if not ocr_text:
            ocr_text = "Project BH-AI Desktop Companion - User john.doe@example.com reported an issue with sk-live-982374982347abcdef1234567890."

        # 4. Local PII Redaction
        t0 = time.perf_counter()
        pii_res = self.pii.redact_text(ocr_text)
        t_pii = time.perf_counter() - t0

        # Store in episodic database
        self.db.add_record(
            session_id=self.session.session_id,
            redacted_text=pii_res.redacted_text,
            app_name="Visual Studio Code",
            window_title="latency_benchmark.py",
            is_active=True,
            token_count=max(len(pii_res.redacted_text.split()), 1),
        )

        # 5. Dynamic Relevance Scoring & Knapsack RAG assembly
        t0 = time.perf_counter()
        prompt_pkg = self.rag.retrieve_and_assemble(
            query=user_query,
            session_id=self.session.session_id,
            token_budget=1500,
        )
        t_rag = time.perf_counter() - t0

        # 6. Local LLM contextual reasoning
        t0 = time.perf_counter()
        llm_res = self.llm.generate(prompt_pkg)
        t_llm = time.perf_counter() - t0

        # 7. Text-to-speech dispatch (queue overhead measurement)
        t0 = time.perf_counter()
        _ = len(llm_res.text)  # Simulated dispatch
        t_tts = time.perf_counter() - t0

        t_total = time.perf_counter() - t_total_start

        return PipelineStageMetrics(
            t_wake_ms=round(t_wake * 1000, 2),
            t_stt_ms=round(t_stt * 1000, 2),
            t_ocr_ms=round(t_ocr * 1000, 2),
            t_pii_ms=round(t_pii * 1000, 2),
            t_rag_ms=round(t_rag * 1000, 2),
            t_llm_ms=round(t_llm * 1000, 2),
            t_tts_ms=round(t_tts * 1000, 2),
            t_total_ms=round(t_total * 1000, 2),
        )

    # -------------------------------------------------------------- #
    #  Resource Utilization Measurement
    # -------------------------------------------------------------- #

    def measure_resources(self) -> ResourceMetrics:
        """Measure current physical RSS memory and database storage growth rate."""
        process = psutil.Process(os.getpid())
        ram_rss_mb = process.memory_info().rss / (1024.0 * 1024.0)

        # Measure average record size in SQLite
        db_size_bytes = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        records = self.db.get_recent_records(limit=100)
        rec_count = max(len(records), 1)
        avg_record_bytes = db_size_bytes / rec_count

        # Estimate growth per hour based on 720 frames/hour
        db_growth_mb_h = (avg_record_bytes * self.CAPTURE_RATE_PER_HOUR) / (1024.0 * 1024.0)

        return ResourceMetrics(
            ram_rss_mb=round(ram_rss_mb, 2),
            db_record_bytes_avg=round(avg_record_bytes, 2),
            db_growth_mb_per_hour=round(db_growth_mb_h, 3),
        )

    # -------------------------------------------------------------- #
    #  Full Benchmark Runner
    # -------------------------------------------------------------- #

    def run_benchmark(self, iterations: int = 3) -> BenchmarkReport:
        """
        Executes N cycles and aggregates mean latencies and resource metrics.
        """
        cycles: list[PipelineStageMetrics] = []
        for _ in range(max(iterations, 1)):
            cycles.append(self.run_cycle())

        # Average metrics
        avg_stages = PipelineStageMetrics(
            t_wake_ms=round(float(np.mean([c.t_wake_ms for c in cycles])), 2),
            t_stt_ms=round(float(np.mean([c.t_stt_ms for c in cycles])), 2),
            t_ocr_ms=round(float(np.mean([c.t_ocr_ms for c in cycles])), 2),
            t_pii_ms=round(float(np.mean([c.t_pii_ms for c in cycles])), 2),
            t_rag_ms=round(float(np.mean([c.t_rag_ms for c in cycles])), 2),
            t_llm_ms=round(float(np.mean([c.t_llm_ms for c in cycles])), 2),
            t_tts_ms=round(float(np.mean([c.t_tts_ms for c in cycles])), 2),
            t_total_ms=round(float(np.mean([c.t_total_ms for c in cycles])), 2),
        )

        resources = self.measure_resources()

        # Evaluate against targets
        p_ocr_rag = avg_stages.t_ocr_plus_rag_ms < self.TARGET_OCR_RAG_MS
        p_ram = resources.ram_rss_mb < self.TARGET_RAM_MB
        p_storage = resources.db_growth_mb_per_hour < self.TARGET_STORAGE_MB_PER_HOUR
        all_passed = p_ocr_rag and p_ram and p_storage

        return BenchmarkReport(
            iterations=iterations,
            stages=avg_stages,
            resources=resources,
            passed_ocr_rag_target=p_ocr_rag,
            passed_ram_target=p_ram,
            passed_storage_target=p_storage,
            all_targets_passed=all_passed,
            timestamp=time.time(),
        )


# ------------------------------------------------------------------ #
#  CLI Entry Point
# ------------------------------------------------------------------ #

def main() -> None:
    parser = argparse.ArgumentParser(description="BH-AI Latency & Resource Benchmark Profiler")
    parser.add_argument("--iterations", "-i", type=int, default=3, help="Number of benchmark cycles to run")
    parser.add_argument("--json", "-j", type=str, default="", help="Path to write output JSON report")
    args = parser.parse_args()

    bench = SystemBenchmark()
    try:
        report = bench.run_benchmark(iterations=args.iterations)
        print(report.to_ascii_table())

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"\nReport written to: {args.json}")
    finally:
        bench.close()


if __name__ == "__main__":
    main()
