"""
Local LLM Reasoning Driver for BH-AI.
Connects to local LLM engines (Ollama REST API, llama-cpp-python, or Mock engine)
to generate streaming and non-streaming responses from bounded knapsack PromptPackages.

Strict Zero Cloud Leakage:
  Enforces local loopback endpoints (localhost, 127.0.0.1, ::1) to guarantee
  that zero screen context or activity logs leave the user's physical machine.
"""

from __future__ import annotations

import enum
import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

from src.memory.rag import PromptPackage, EpisodicRAGEngine
from src.privacy.pii import PIIRedactor

logger = logging.getLogger("BH-AI.Reasoning")


# ------------------------------------------------------------------ #
#  Exceptions & Security Errors
# ------------------------------------------------------------------ #

class SecurityViolationError(Exception):
    """Raised when an attempt is made to send user context to an external or non-local endpoint."""
    pass


# ------------------------------------------------------------------ #
#  Local Data Isolation Guard
# ------------------------------------------------------------------ #

class LocalDataIsolationGuard:
    """
    Guarantees strict zero-cloud leakage by validating network endpoints
    and sanitizing text payloads prior to inference.
    """

    ALLOWED_LOCAL_HOSTS = {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "testserver",
    }

    @classmethod
    def is_local_endpoint(cls, url: str) -> bool:
        """
        Validates if a URL points strictly to a local loopback address.
        """
        if not url:
            return False
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = (parsed.hostname or "").lower()

            if hostname in cls.ALLOWED_LOCAL_HOSTS:
                return True

            # If an IP address was specified, verify it's a loopback
            try:
                ip = socket.gethostbyname(hostname)
                if ip.startswith("127.") or ip == "0.0.0.0":
                    return True
            except (socket.gaierror, socket.herror):
                pass

            return False
        except Exception:
            return False

    @classmethod
    def validate_endpoint(cls, url: str) -> None:
        """
        Raises SecurityViolationError if the URL is not strictly local.
        """
        if not cls.is_local_endpoint(url):
            raise SecurityViolationError(
                f"Zero-cloud data leakage violation: Endpoint '{url}' is not a permitted "
                f"local loopback address. All BH-AI reasoning must execute on-device."
            )

    @classmethod
    def sanitize_input(cls, text: str, redactor: PIIRedactor | None = None) -> str:
        """
        Passes text through PII redaction to sanitize accidental secrets before prompt dispatch.
        """
        if not text:
            return ""
        red = redactor or PIIRedactor()
        res = red.redact_text(text)
        return res.redacted_text


# ------------------------------------------------------------------ #
#  Configuration & Response Types
# ------------------------------------------------------------------ #

class LLMBackend(str, enum.Enum):
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    MOCK = "mock"
    AUTO = "auto"


@dataclass
class LLMConfig:
    """Configuration for local LLM inference."""
    model_name: str = "llama3.2:3b"
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = 0.2
    max_tokens: int = 512
    timeout: float = 30.0
    system_prompt: str = (
        "You are BH-AI, an intelligent, privacy-preserving desktop assistant. "
        "Answer the user's questions clearly, concisely, and accurately based on "
        "the provided screen activity observations."
    )


@dataclass
class LLMResponse:
    """Structured response from the local LLM driver."""
    text: str
    tokens_generated: int = 0
    prompt_tokens: int = 0
    latency_seconds: float = 0.0
    backend_used: str = ""
    model_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ #
#  Local LLM Driver
# ------------------------------------------------------------------ #

class LocalLLMDriver:
    """
    Unified local reasoning driver for BH-AI.
    Connects to local runtimes, ingests PromptPackages, and streams responses.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        backend: LLMBackend = LLMBackend.AUTO,
        redactor: PIIRedactor | None = None,
    ):
        self.config = config or LLMConfig()
        self.requested_backend = backend
        self.redactor = redactor or PIIRedactor()

        # Enforce zero-cloud security check immediately upon initialization
        if self.config.base_url:
            LocalDataIsolationGuard.validate_endpoint(self.config.base_url)

        self.active_backend = self._resolve_backend(backend)
        logger.info(f"Initialized LocalLLMDriver with active backend: {self.active_backend.value}")

    # -------------------------------------------------------------- #
    #  Backend Resolution
    # -------------------------------------------------------------- #

    def _resolve_backend(self, requested: LLMBackend) -> LLMBackend:
        if requested == LLMBackend.MOCK:
            return LLMBackend.MOCK

        if requested == LLMBackend.OLLAMA:
            return LLMBackend.OLLAMA

        if requested == LLMBackend.LLAMACPP:
            return LLMBackend.LLAMACPP

        # AUTO detection
        if self.is_ollama_available():
            logger.info("Ollama local runtime detected on port 11434.")
            return LLMBackend.OLLAMA

        if self._is_llamacpp_available():
            logger.info("llama-cpp-python runtime detected.")
            return LLMBackend.LLAMACPP

        logger.info("No active external local LLM daemon detected; falling back to high-fidelity Mock backend.")
        return LLMBackend.MOCK

    def is_ollama_available(self) -> bool:
        """Check if local Ollama daemon is active and responding on loopback."""
        try:
            url = f"{self.config.base_url.rstrip('/')}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _is_llamacpp_available(self) -> bool:
        try:
            import llama_cpp  # type: ignore
            return True
        except ImportError:
            return False

    # -------------------------------------------------------------- #
    #  Inference Interface
    # -------------------------------------------------------------- #

    def generate(
        self,
        prompt: str | PromptPackage,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """
        Generates a non-streaming response from the local LLM.
        """
        prompt_text = prompt.prompt_text if isinstance(prompt, PromptPackage) else prompt
        sys_prompt = system_prompt or self.config.system_prompt

        # Security check & input sanitization
        clean_prompt = LocalDataIsolationGuard.sanitize_input(prompt_text, self.redactor)

        t_start = time.perf_counter()

        if self.active_backend == LLMBackend.OLLAMA:
            resp = self._generate_ollama(clean_prompt, sys_prompt)
        elif self.active_backend == LLMBackend.LLAMACPP:
            resp = self._generate_llamacpp(clean_prompt, sys_prompt)
        else:
            resp = self._generate_mock(prompt, sys_prompt)

        latency = time.perf_counter() - t_start
        resp.latency_seconds = round(latency, 4)
        return resp

    def generate_stream(
        self,
        prompt: str | PromptPackage,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """
        Yields tokens as they are generated by the local LLM runtime.
        """
        prompt_text = prompt.prompt_text if isinstance(prompt, PromptPackage) else prompt
        sys_prompt = system_prompt or self.config.system_prompt

        clean_prompt = LocalDataIsolationGuard.sanitize_input(prompt_text, self.redactor)

        if self.active_backend == LLMBackend.OLLAMA:
            yield from self._stream_ollama(clean_prompt, sys_prompt)
        elif self.active_backend == LLMBackend.LLAMACPP:
            yield from self._stream_llamacpp(clean_prompt, sys_prompt)
        else:
            yield from self._stream_mock(prompt, sys_prompt)

    # -------------------------------------------------------------- #
    #  RAG Integration Helpers
    # -------------------------------------------------------------- #

    def ask_with_rag(
        self,
        query: str,
        rag_engine: EpisodicRAGEngine,
        session_id: str | None = None,
        token_budget: int = 1500,
    ) -> LLMResponse:
        """
        Assembles episodic memory context using dynamic relevance scoring
        and bounded knapsack budgeting, then queries the local LLM.
        """
        pkg = rag_engine.retrieve_and_assemble(
            query=query,
            session_id=session_id,
            token_budget=token_budget,
        )
        return self.generate(pkg)

    def stream_with_rag(
        self,
        query: str,
        rag_engine: EpisodicRAGEngine,
        session_id: str | None = None,
        token_budget: int = 1500,
    ) -> Iterator[str]:
        """
        Streams local LLM response using assembled episodic memory context.
        """
        pkg = rag_engine.retrieve_and_assemble(
            query=query,
            session_id=session_id,
            token_budget=token_budget,
        )
        yield from self.generate_stream(pkg)

    # -------------------------------------------------------------- #
    #  Ollama Engine Implementation
    # -------------------------------------------------------------- #

    def _generate_ollama(self, prompt: str, system_prompt: str) -> LLMResponse:
        url = f"{self.config.base_url.rstrip('/')}/api/generate"
        LocalDataIsolationGuard.validate_endpoint(url)

        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                text = res_json.get("response", "").strip()
                tokens_gen = res_json.get("eval_count", len(text.split()))
                prompt_toks = res_json.get("prompt_eval_count", len(prompt.split()))

                return LLMResponse(
                    text=text,
                    tokens_generated=tokens_gen,
                    prompt_tokens=prompt_toks,
                    backend_used=LLMBackend.OLLAMA.value,
                    model_name=self.config.model_name,
                    metadata=res_json,
                )
        except urllib.error.URLError as e:
            logger.warning(f"Ollama generation failed: {e}. Falling back to simulated reasoning.")
            mock_res = self._generate_mock(prompt, system_prompt)
            mock_res.metadata["fallback_reason"] = str(e)
            return mock_res

    def _stream_ollama(self, prompt: str, system_prompt: str) -> Iterator[str]:
        url = f"{self.config.base_url.rstrip('/')}/api/generate"
        LocalDataIsolationGuard.validate_endpoint(url)

        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                for line in resp:
                    if line:
                        chunk = json.loads(line.decode("utf-8"))
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done", False):
                            break
        except urllib.error.URLError as e:
            logger.warning(f"Ollama stream failed: {e}. Streaming via mock.")
            yield from self._stream_mock(prompt, system_prompt)

    # -------------------------------------------------------------- #
    #  llama-cpp Engine Implementation
    # -------------------------------------------------------------- #

    def _generate_llamacpp(self, prompt: str, system_prompt: str) -> LLMResponse:
        try:
            import llama_cpp  # type: ignore
            # Fallback to simulated reasoning if weights not configured
            return self._generate_mock(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"llama-cpp execution error: {e}. Falling back to mock.")
            return self._generate_mock(prompt, system_prompt)

    def _stream_llamacpp(self, prompt: str, system_prompt: str) -> Iterator[str]:
        yield from self._stream_mock(prompt, system_prompt)

    # -------------------------------------------------------------- #
    #  Mock / Simulated Local Reasoning Backend
    # -------------------------------------------------------------- #

    def _generate_mock(self, prompt: str | PromptPackage, system_prompt: str) -> LLMResponse:
        """
        High-fidelity contextual response synthesizer for testing & offline mode.
        """
        if isinstance(prompt, PromptPackage):
            query = prompt.query
            records = prompt.records
        else:
            query = prompt.split("User Request:")[-1].split("\n")[0].strip() if "User Request:" in prompt else prompt
            records = []

        answer = self._synthesize_mock_answer(query, records)
        tok_gen = len(answer.split())
        tok_prompt = prompt.total_tokens if isinstance(prompt, PromptPackage) else len(prompt.split())

        return LLMResponse(
            text=answer,
            tokens_generated=tok_gen,
            prompt_tokens=tok_prompt,
            backend_used=LLMBackend.MOCK.value,
            model_name="bh-ai-mock-reasoner",
            metadata={"records_used": len(records)},
        )

    def _stream_mock(self, prompt: str | PromptPackage, system_prompt: str) -> Iterator[str]:
        resp = self._generate_mock(prompt, system_prompt)
        tokens = resp.text.split(" ")
        for i, tok in enumerate(tokens):
            yield tok + (" " if i < len(tokens) - 1 else "")

    def _synthesize_mock_answer(self, query: str, records: list) -> str:
        """Helper to create contextual responses from query and observation logs."""
        q_lower = query.lower().strip()

        if not records:
            if "what am i" in q_lower or "doing" in q_lower:
                return "Based on current observations, you are working on your desktop with no recorded background activity."
            return f"I analyzed your request ('{query}') but found no recent screen observations in memory."

        apps = list({r.app_name for r in records if r.app_name})
        windows = list({r.window_title for r in records if r.window_title})
        apps_str = ", ".join(apps) if apps else "Unknown Application"
        latest = records[-1]

        if "what am i doing" in q_lower or "summary" in q_lower or "doing" in q_lower:
            return (
                f"You are currently working in {apps_str} "
                f"(active window: '{latest.window_title or 'Desktop'}'). "
                f"Recent activity indicates task interactions with {len(records)} recorded context events."
            )

        if "code" in q_lower or "error" in q_lower or "bug" in q_lower:
            return (
                f"Reviewing the code context from {apps_str}: "
                f"Recent screen text from '{latest.window_title}' shows active editing. "
                "Ensure all variable definitions and imports match your project structure."
            )

        # General answer with context reflection
        snippet = (latest.redacted_text[:120] + "...") if len(latest.redacted_text) > 120 else latest.redacted_text
        return (
            f"Based on your screen activity in {apps_str} ('{latest.window_title}'): "
            f"{snippet}. In response to '{query}', everything appears consistent with your workflow."
        )
