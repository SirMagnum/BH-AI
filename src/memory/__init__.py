"""
BH-AI Memory Store & 3-Tier Episodic RAG Package.
"""

from src.memory.db import (
    MemoryDatabase,
    SessionRecord,
    ActivityRecord,
    serialize_embedding,
    deserialize_embedding,
)
from src.memory.embeddings import (
    EmbeddingEngine,
    EmbeddingBackend,
    cosine_similarity,
)
from src.memory.rag import (
    EpisodicRAGEngine,
    PromptPackage,
    ScoredRecord,
    compute_relevance_score,
)

__all__ = [
    "MemoryDatabase",
    "SessionRecord",
    "ActivityRecord",
    "serialize_embedding",
    "deserialize_embedding",
    "EmbeddingEngine",
    "EmbeddingBackend",
    "cosine_similarity",
    "EpisodicRAGEngine",
    "PromptPackage",
    "ScoredRecord",
    "compute_relevance_score",
]
