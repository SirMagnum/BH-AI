"""
Unit tests for System Latency Profiler & Benchmark Suite (src/benchmark.py).
Verifies:
  1. Synthetic pipeline stage latency calculation.
  2. RAM and SQLite storage growth rate estimation.
  3. Scorecard target evaluation logic (T_OCR + T_RAG < 300ms, RAM < 200MB, storage < 5MB/h).
  4. ASCII table and JSON serialization of BenchmarkReport.
"""

import json
import unittest

from src.benchmark import (
    PipelineStageMetrics,
    ResourceMetrics,
    BenchmarkReport,
    SystemBenchmark,
)


class TestBenchmark(unittest.TestCase):

    def setUp(self):
        self.bench = SystemBenchmark()

    def tearDown(self):
        self.bench.close()

    def test_pipeline_stage_metrics_properties(self):
        metrics = PipelineStageMetrics(
            t_wake_ms=5.0,
            t_stt_ms=10.0,
            t_ocr_ms=45.0,
            t_pii_ms=4.0,
            t_rag_ms=15.0,
            t_llm_ms=25.0,
            t_tts_ms=1.0,
            t_total_ms=105.0,
        )
        self.assertEqual(metrics.t_ocr_plus_rag_ms, 60.0)  # 45 + 15
        self.assertEqual(metrics.t_total_ms, 105.0)

    def test_benchmark_report_serialization(self):
        stages = PipelineStageMetrics(
            t_wake_ms=2.0,
            t_stt_ms=5.0,
            t_ocr_ms=50.0,
            t_pii_ms=3.0,
            t_rag_ms=20.0,
            t_llm_ms=30.0,
            t_tts_ms=1.0,
            t_total_ms=111.0,
        )
        resources = ResourceMetrics(
            ram_rss_mb=95.0,
            db_record_bytes_avg=1200.0,
            db_growth_mb_per_hour=0.82,
        )
        report = BenchmarkReport(
            iterations=1,
            stages=stages,
            resources=resources,
            passed_ocr_rag_target=True,
            passed_ram_target=True,
            passed_storage_target=True,
            all_targets_passed=True,
            timestamp=1700000000.0,
        )

        d = report.to_dict()
        self.assertTrue(d["all_targets_passed"])
        self.assertEqual(d["stages"]["t_ocr_ms"], 50.0)
        self.assertEqual(d["resources"]["ram_rss_mb"], 95.0)

        # Verify JSON dump
        json_str = json.dumps(d)
        self.assertIn("all_targets_passed", json_str)

        # Verify ASCII table format
        table = report.to_ascii_table()
        self.assertIn("BH-AI SYSTEM LATENCY & RESOURCE BENCHMARK", table)
        self.assertIn("ALL TARGETS PASSED", table)
        self.assertIn("T_OCR + T_RAG Target", table)

    def test_run_cycle(self):
        metrics = self.bench.run_cycle()
        self.assertIsInstance(metrics, PipelineStageMetrics)
        self.assertGreater(metrics.t_ocr_ms, 0.0)
        self.assertGreater(metrics.t_rag_ms, 0.0)
        self.assertGreater(metrics.t_total_ms, 0.0)

    def test_measure_resources(self):
        # Run one cycle to write a record into the DB
        self.bench.run_cycle()
        res = self.bench.measure_resources()

        self.assertIsInstance(res, ResourceMetrics)
        self.assertGreater(res.ram_rss_mb, 10.0)      # Physical process RSS > 10 MB
        self.assertGreater(res.db_record_bytes_avg, 0.0)
        self.assertGreater(res.db_growth_mb_per_hour, 0.0)

    def test_run_benchmark_aggregated(self):
        report = self.bench.run_benchmark(iterations=2)

        self.assertIsInstance(report, BenchmarkReport)
        self.assertEqual(report.iterations, 2)
        # Verify OCR + RAG latency is well within target for synthetic load
        self.assertTrue(report.stages.t_ocr_plus_rag_ms < 300.0)
        self.assertTrue(report.passed_ocr_rag_target)


if __name__ == "__main__":
    unittest.main()
