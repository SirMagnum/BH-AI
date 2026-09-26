"""
Automated unit tests for Local LLM Reasoning Driver (src/reasoning/llm.py).
Verifies:
  1. LocalDataIsolationGuard enforces strict loopback and zero cloud leakage.
  2. PII sanitization of prompts prior to inference.
  3. LocalLLMDriver initialization, auto fallback to Mock backend.
  4. Contextual Mock reasoning generation and streaming.
  5. End-to-end RAG integration with EpisodicRAGEngine.
  6. Live mock HTTP server verifying Ollama REST API request formatting and stream decoding.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler

from src.memory.db import MemoryDatabase, ActivityRecord
from src.memory.embeddings import EmbeddingEngine
from src.memory.rag import EpisodicRAGEngine
from src.privacy.pii import PIIRedactor
from src.reasoning.llm import (
    LocalLLMDriver,
    LLMBackend,
    LLMConfig,
    LLMResponse,
    LocalDataIsolationGuard,
    SecurityViolationError,
)


class TestLocalDataIsolationGuard(unittest.TestCase):
    """Test zero-cloud data leakage enforcement and PII prompt sanitization."""

    def test_local_endpoints_accepted(self):
        valid_local = [
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://127.0.0.1:8000/v1",
            "http://0.0.0.0:11434",
            "http://[::1]:11434",
            "http://testserver",
        ]
        for url in valid_local:
            with self.subTest(url=url):
                self.assertTrue(LocalDataIsolationGuard.is_local_endpoint(url))
                # validate_endpoint should not raise
                LocalDataIsolationGuard.validate_endpoint(url)

    def test_external_cloud_endpoints_rejected(self):
        external_urls = [
            "https://api.openai.com/v1",
            "https://api.anthropic.com/v1/messages",
            "http://8.8.8.8:8080/api",
            "https://example.com/llm",
            "http://192.168.1.50:11434",  # remote LAN endpoint blocked by strict loopback policy
        ]
        for url in external_urls:
            with self.subTest(url=url):
                self.assertFalse(LocalDataIsolationGuard.is_local_endpoint(url))
                with self.assertRaises(SecurityViolationError):
                    LocalDataIsolationGuard.validate_endpoint(url)

    def test_driver_rejects_external_base_url_on_init(self):
        cfg = LLMConfig(base_url="https://api.openai.com/v1")
        with self.assertRaises(SecurityViolationError):
            LocalLLMDriver(config=cfg, backend=LLMBackend.MOCK)

    def test_prompt_sanitization_removes_raw_pii(self):
        raw = "User email is admin@company.com and secret key is sk-abcdef1234567890abcdef1234567890"
        clean = LocalDataIsolationGuard.sanitize_input(raw)
        self.assertNotIn("admin@company.com", clean)
        self.assertNotIn("sk-abcdef1234567890abcdef1234567890", clean)
        self.assertIn("[EMAIL_ADDR_", clean)


class TestLocalLLMDriverMock(unittest.TestCase):
    """Test LocalLLMDriver operating with the high-fidelity mock backend."""

    def setUp(self):
        self.driver = LocalLLMDriver(backend=LLMBackend.MOCK)

    def test_driver_initialization(self):
        self.assertEqual(self.driver.active_backend, LLMBackend.MOCK)

    def test_auto_backend_falls_back_when_offline(self):
        # Using an unused port so Ollama is definitely offline
        cfg = LLMConfig(base_url="http://127.0.0.1:59999")
        driver = LocalLLMDriver(config=cfg, backend=LLMBackend.AUTO)
        self.assertEqual(driver.active_backend, LLMBackend.MOCK)

    def test_generate_simple_prompt(self):
        prompt = "What is the status of my system?"
        resp = self.driver.generate(prompt)

        self.assertIsInstance(resp, LLMResponse)
        self.assertTrue(len(resp.text) > 0)
        self.assertEqual(resp.backend_used, LLMBackend.MOCK.value)
        self.assertTrue(resp.latency_seconds >= 0.0)

    def test_generate_stream(self):
        prompt = "Explain current task"
        tokens = list(self.driver.generate_stream(prompt))

        self.assertTrue(len(tokens) > 1)
        full_text = "".join(tokens)
        self.assertTrue(len(full_text.strip()) > 0)


class TestLLMEndToEndRAG(unittest.TestCase):
    """Verify integration between EpisodicRAGEngine and LocalLLMDriver."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_rag_llm.db")
        self.db = MemoryDatabase(self.db_path)
        self.embeddings = EmbeddingEngine(backend="tfidf_semantic")
        self.rag = EpisodicRAGEngine(db=self.db, embeddings=self.embeddings)
        self.driver = LocalLLMDriver(backend=LLMBackend.MOCK)

        # Seed database with a session and activity records
        session = self.db.start_session("session_llm_test")
        now = time.time()

        self.db.add_record(
            session_id=session.session_id,
            timestamp=now - 20,
            app_name="Visual Studio Code",
            window_title="main.py - Project",
            redacted_text="def process_payment(): validate_cart() calculate_tax()",
            is_active=True,
            token_count=15,
        )
        self.db.add_record(
            session_id=session.session_id,
            timestamp=now - 5,
            app_name="Google Chrome",
            window_title="FastAPI Documentation - Endpoints",
            redacted_text="FastAPI request validation with Pydantic models and dependency injection",
            is_active=True,
            token_count=18,
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ask_with_rag(self):
        query = "What code was I editing?"
        response = self.driver.ask_with_rag(query, self.rag, session_id="session_llm_test")

        self.assertIsInstance(response, LLMResponse)
        self.assertIn("Visual Studio Code", response.text)
        self.assertTrue(response.metadata.get("records_used", 0) > 0)

    def test_stream_with_rag(self):
        query = "What am I doing right now?"
        tokens = list(self.driver.stream_with_rag(query, self.rag, session_id="session_llm_test"))

        self.assertTrue(len(tokens) > 0)
        reconstructed = "".join(tokens)
        self.assertTrue("Visual Studio Code" in reconstructed or "Google Chrome" in reconstructed)


# ------------------------------------------------------------------ #
#  Simulated Ollama HTTP Server for Live Protocol Testing
# ------------------------------------------------------------------ #

class MockOllamaHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler simulating Ollama's REST endpoints."""

    def log_message(self, format, *args):
        pass  # Quiet test logging

    def do_GET(self):
        if self.path == "/api/tags":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"models": [{"name": "llama3.2:3b"}]}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/generate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            stream = body.get("stream", False)

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                chunks = [
                    b'{"response": "Local ", "done": false}\n',
                    b'{"response": "reasoning ", "done": false}\n',
                    b'{"response": "completed.", "done": true, "eval_count": 3}\n',
                ]
                for c in chunks:
                    self.wfile.write(c)
                    self.wfile.flush()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                res = {
                    "response": "Local reasoning completed.",
                    "eval_count": 3,
                    "prompt_eval_count": 10,
                    "done": True,
                }
                self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class TestLiveOllamaProtocol(unittest.TestCase):
    """Test actual HTTP dispatch to a mock Ollama server over 127.0.0.1 loopback."""

    @classmethod
    def setUpClass(cls):
        # Start ephemeral local server on loopback
        cls.server = HTTPServer(("127.0.0.1", 0), MockOllamaHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ollama_generate_roundtrip(self):
        base_url = f"http://127.0.0.1:{self.port}"
        cfg = LLMConfig(base_url=base_url)
        driver = LocalLLMDriver(config=cfg, backend=LLMBackend.OLLAMA)

        self.assertEqual(driver.active_backend, LLMBackend.OLLAMA)
        self.assertTrue(driver.is_ollama_available())

        resp = driver.generate("Test prompt")
        self.assertEqual(resp.text, "Local reasoning completed.")
        self.assertEqual(resp.tokens_generated, 3)
        self.assertEqual(resp.backend_used, LLMBackend.OLLAMA.value)

    def test_ollama_stream_roundtrip(self):
        base_url = f"http://127.0.0.1:{self.port}"
        cfg = LLMConfig(base_url=base_url)
        driver = LocalLLMDriver(config=cfg, backend=LLMBackend.OLLAMA)

        tokens = list(driver.generate_stream("Stream test"))
        self.assertEqual(tokens, ["Local ", "reasoning ", "completed."])


if __name__ == "__main__":
    unittest.main()
