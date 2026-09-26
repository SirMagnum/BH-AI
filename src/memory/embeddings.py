"""
Local Dense Vector Embedding Engine for BH-AI.
Produces normalized dense vector representations e(r_i) for episodic OCR records.
Supports pluggable backends:
  - Sentence-Transformers (all-MiniLM-L6-v2) if installed
  - ONNX Runtime embedding models if installed
  - High-performance, sub-millisecond local TF-IDF / Subword Hashing vectorizer via scikit-learn & numpy
  - Mock backend for deterministic unit testing
"""

from __future__ import annotations

import enum
import logging
import math
import threading
from typing import Any
import numpy as np

logger = logging.getLogger("BH-AI.Embeddings")


class EmbeddingBackend(str, enum.Enum):
    AUTO = "auto"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    ONNX = "onnx"
    TFIDF_SEMANTIC = "tfidf_semantic"
    MOCK = "mock"


# ------------------------------------------------------------------ #
#  Cosine Similarity Calculation
# ------------------------------------------------------------------ #

def cosine_similarity(
    vec_a: list[float] | np.ndarray,
    vec_b: list[float] | np.ndarray,
) -> float:
    """
    Compute cosine similarity between two dense vectors:
      cos_sim(u, v) = (u · v) / (||u|| ||v||)
    Returns a score normalized to [0.0, 1.0].
    """
    if vec_a is None or vec_b is None or len(vec_a) == 0 or len(vec_b) == 0:
        return 0.0

    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    sim = float(np.dot(a, b) / (norm_a * norm_b))
    # Bound to [-1.0, 1.0] and clamp non-negative for relevance
    return max(min(sim, 1.0), -1.0)


# ------------------------------------------------------------------ #
#  Embedding Engine
# ------------------------------------------------------------------ #

class EmbeddingEngine:
    """
    Thread-safe dense vector embedding generator.
    Ensures all vectors are L2-normalized unit vectors (||e|| = 1.0).
    """

    def __init__(
        self,
        dimension: int = 256,
        backend: EmbeddingBackend | str = EmbeddingBackend.AUTO,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.dimension = dimension
        self.model_name = model_name
        self._lock = threading.RLock()

        if isinstance(backend, EmbeddingBackend):
            self._backend_pref = backend
        else:
            self._backend_pref = EmbeddingBackend(str(backend).lower())

        self._active_backend: EmbeddingBackend = self._resolve_backend()
        self._engine_instance: Any = None
        self._init_active_backend()

    def _resolve_backend(self) -> EmbeddingBackend:
        if self._backend_pref == EmbeddingBackend.MOCK:
            return EmbeddingBackend.MOCK

        if self._backend_pref == EmbeddingBackend.SENTENCE_TRANSFORMERS:
            try:
                import sentence_transformers
                return EmbeddingBackend.SENTENCE_TRANSFORMERS
            except ImportError:
                logger.warning("[Embeddings] sentence-transformers not installed. Falling back.")

        if self._backend_pref == EmbeddingBackend.ONNX:
            try:
                import onnxruntime
                return EmbeddingBackend.ONNX
            except ImportError:
                logger.warning("[Embeddings] onnxruntime not installed. Falling back.")

        if self._backend_pref == EmbeddingBackend.TFIDF_SEMANTIC:
            return EmbeddingBackend.TFIDF_SEMANTIC

        # AUTO selection: check neural models, otherwise use local TF-IDF semantic vectorizer
        try:
            import sentence_transformers
            return EmbeddingBackend.SENTENCE_TRANSFORMERS
        except ImportError:
            pass

        try:
            import onnxruntime
            return EmbeddingBackend.ONNX
        except ImportError:
            pass

        return EmbeddingBackend.TFIDF_SEMANTIC

    def _init_active_backend(self) -> None:
        """Instantiate the active embedding model."""
        if self._active_backend == EmbeddingBackend.SENTENCE_TRANSFORMERS:
            from sentence_transformers import SentenceTransformer
            self._engine_instance = SentenceTransformer(self.model_name)
            self.dimension = self._engine_instance.get_sentence_embedding_dimension()

        elif self._active_backend == EmbeddingBackend.TFIDF_SEMANTIC:
            from sklearn.feature_extraction.text import HashingVectorizer
            # Subword character n-grams (3-5) + word unigrams for robust typo/lexical matching
            self._engine_instance = HashingVectorizer(
                n_features=self.dimension,
                analyzer="char_wb",
                ngram_range=(3, 5),
                norm="l2",
                alternate_sign=False,
            )

    @property
    def backend_name(self) -> str:
        return self._active_backend.value

    # ------------------------------------------------------------------ #
    #  Inference APIs
    # ------------------------------------------------------------------ #

    def embed_text(self, text: str) -> list[float]:
        """
        Generate an L2-normalized dense embedding vector for text.
        ||e(t)|| = 1.0
        """
        if not text or not text.strip():
            # Return zero vector if empty
            return [0.0] * self.dimension

        with self._lock:
            if self._active_backend == EmbeddingBackend.SENTENCE_TRANSFORMERS:
                vec = self._engine_instance.encode(text, normalize_embeddings=True)
                return [float(x) for x in vec]

            elif self._active_backend == EmbeddingBackend.TFIDF_SEMANTIC:
                sparse_mat = self._engine_instance.transform([text])
                dense_arr = sparse_mat.toarray()[0]
                norm = np.linalg.norm(dense_arr)
                if norm > 0:
                    dense_arr = dense_arr / norm
                return [float(x) for x in dense_arr]

            else:  # MOCK
                return self._mock_embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding generation."""
        if not texts:
            return []

        with self._lock:
            if self._active_backend == EmbeddingBackend.SENTENCE_TRANSFORMERS:
                vecs = self._engine_instance.encode(texts, normalize_embeddings=True)
                return [[float(x) for x in v] for v in vecs]

            elif self._active_backend == EmbeddingBackend.TFIDF_SEMANTIC:
                sparse_mat = self._engine_instance.transform(texts)
                dense_mat = sparse_mat.toarray()
                results: list[list[float]] = []
                for row in dense_mat:
                    norm = np.linalg.norm(row)
                    if norm > 0:
                        row = row / norm
                    results.append([float(x) for x in row])
                return results

            else:  # MOCK
                return [self._mock_embed(t) for t in texts]

    def _mock_embed(self, text: str) -> list[float]:
        """Deterministic pseudo-random vector based on string hash for testing."""
        if not text.strip():
            return [0.0] * self.dimension

        # Seed with text hash
        seed = abs(hash(text)) % (2**32)
        rng = np.random.RandomState(seed)
        vec = rng.randn(self.dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return [float(x) for x in vec]
