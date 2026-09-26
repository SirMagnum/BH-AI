"""
Episodic RAG Engine for BH-AI.
Implements the dynamic time-decay relevance scoring formula and bounded knapsack
token optimization to assemble prompt packages P_B for local LLM reasoning.

Mathematical Formulations:
  Relevance Score:
    S(r_i, q, t) = [α · cos_sim(e(r_i), e(q)) + (1 - α) · I_active(r_i)] · exp(-λ (t - t_i))

  Bounded Knapsack Prompt Assembly:
    max_{X ⊆ R} ∑_{r_i ∈ X} S(r_i, q, t)  subject to  ∑_{r_i ∈ X} len_tokens(r_i) ≤ B
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from src.memory.db import MemoryDatabase, ActivityRecord
from src.memory.embeddings import EmbeddingEngine, cosine_similarity

logger = logging.getLogger("BH-AI.RAG")


# ------------------------------------------------------------------ #
#  Data Models
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class ScoredRecord:
    """An activity record paired with its calculated relevance score."""
    record: ActivityRecord
    score: float
    cosine_sim: float
    time_decay: float


@dataclass(frozen=True)
class PromptPackage:
    """Formatted prompt payload P_B ready for local LLM inference."""
    prompt_text: str
    query: str
    records: list[ActivityRecord]
    total_tokens: int
    token_budget: int
    assembled_at: float


# ------------------------------------------------------------------ #
#  Relevance Scoring Formula
# ------------------------------------------------------------------ #

def compute_relevance_score(
    record_embedding: list[float] | None,
    query_embedding: list[float],
    is_active_window: bool,
    timestamp: float,
    current_time: float,
    alpha: float = 0.7,
    lambda_decay: float = 0.001,
) -> tuple[float, float, float]:
    """
    Computes S(r_i, q, t) = [α · cos_sim(e(r_i), e(q)) + (1 - α) · I_active(r_i)] · exp(-λ (t - t_i))
    Returns tuple: (total_score, cosine_similarity, time_decay_factor)
    """
    # 1. Cosine similarity
    cos_sim = cosine_similarity(record_embedding, query_embedding) if record_embedding else 0.0
    cos_sim = max(cos_sim, 0.0)  # non-negative relevance

    # 2. Active window indicator
    i_active = 1.0 if is_active_window else 0.0

    # 3. Context relevance combination
    context_score = (alpha * cos_sim) + ((1.0 - alpha) * i_active)

    # 4. Exponential time decay: exp(-λ (t - t_i))
    delta_t = max(current_time - timestamp, 0.0)
    decay_factor = math.exp(-lambda_decay * delta_t)

    # 5. Composite score
    total_score = context_score * decay_factor
    return total_score, cos_sim, decay_factor


# ------------------------------------------------------------------ #
#  Episodic RAG Engine
# ------------------------------------------------------------------ #

class EpisodicRAGEngine:
    """
    3-Tier Session RAG engine providing dynamic scoring and knapsack prompt budgeting.
    """

    SYSTEM_PROMPT_TEMPLATE = (
        "You are BH-AI, an intelligent desktop assistant with privacy-aware observation.\n"
        "All sensitive data (emails, credentials, cards) has been sanitized locally.\n"
        "Use the recent screen observations below to answer the user's request accurately.\n\n"
        "--- OBSERVATION CONTEXT ---\n"
        "{context_logs}\n"
        "--- END CONTEXT ---\n\n"
        "User Request: {query}\n"
        "Provide a clear, helpful response:"
    )

    def __init__(
        self,
        db: MemoryDatabase,
        embeddings: EmbeddingEngine | None = None,
        alpha: float = 0.7,
        lambda_decay: float = 0.001,
    ):
        """
        :param db: SQLite MemoryDatabase instance
        :param embeddings: Dense vector EmbeddingEngine
        :param alpha: Weight balancing semantic similarity (α) vs active window bias (1-α)
        :param lambda_decay: Time decay coefficient λ
        """
        self.db = db
        self.embeddings = embeddings or EmbeddingEngine()
        self.alpha = min(max(alpha, 0.0), 1.0)
        self.lambda_decay = max(lambda_decay, 0.0)

    def score_record(
        self,
        record: ActivityRecord,
        query_embedding: list[float],
        current_time: float | None = None,
    ) -> ScoredRecord:
        """Score a single activity record against a query embedding."""
        t_now = current_time if current_time is not None else time.time()
        score, cos_sim, decay = compute_relevance_score(
            record_embedding=record.embedding,
            query_embedding=query_embedding,
            is_active_window=record.is_active_window,
            timestamp=record.timestamp,
            current_time=t_now,
            alpha=self.alpha,
            lambda_decay=self.lambda_decay,
        )
        return ScoredRecord(
            record=record,
            score=score,
            cosine_sim=cos_sim,
            time_decay=decay,
        )

    def solve_bounded_knapsack(
        self,
        scored_records: list[ScoredRecord],
        token_budget: int,
    ) -> list[ActivityRecord]:
        """
        Solve bounded knapsack: max ∑ S(r_i) subject to ∑ len_tokens(r_i) ≤ B.
        Uses density-based greedy heuristic: rank by (score / token_count).
        """
        if not scored_records or token_budget <= 0:
            return []

        # Sort by value density (score / weight) descending
        # Add small epsilon to avoid div by zero
        sorted_candidates = sorted(
            scored_records,
            key=lambda item: item.score / max(item.record.token_count, 1),
            reverse=True,
        )

        selected: list[ActivityRecord] = []
        tokens_used = 0

        for item in sorted_candidates:
            cost = max(item.record.token_count, 1)
            if tokens_used + cost <= token_budget:
                selected.append(item.record)
                tokens_used += cost

        # Return selected records sorted chronologically for coherent LLM context
        selected.sort(key=lambda r: r.timestamp)
        return selected

    def retrieve_and_assemble(
        self,
        query: str,
        session_id: str | None = None,
        token_budget: int = 1500,
        candidate_limit: int = 150,
        current_time: float | None = None,
    ) -> PromptPackage:
        """
        Full RAG pipeline:
          1. Embed user query e(q).
          2. Fetch candidate records from episodic store.
          3. Calculate dynamic relevance score S(r_i, q, t) with time-decay.
          4. Solve bounded knapsack for token budget B.
          5. Assemble prompt package P_B.
        """
        t_now = current_time if current_time is not None else time.time()

        # 1. Embed query
        query_vec = self.embeddings.embed_text(query)

        # 2. Candidate records
        if session_id:
            candidates = self.db.get_session_records(session_id, limit=candidate_limit)
        else:
            candidates = self.db.get_recent_records(limit=candidate_limit)

        # If records lack embeddings, generate and save them lazily
        for rec in candidates:
            if rec.embedding is None and rec.redacted_text:
                emb = self.embeddings.embed_text(rec.redacted_text)
                self.db.update_record_embedding(rec.record_id, emb)
                # Update local object reference
                object.__setattr__(rec, "embedding", emb)

        # 3. Score candidates
        scored = [
            self.score_record(rec, query_vec, current_time=t_now)
            for rec in candidates
        ]

        # 4. Knapsack budget allocation
        # Reserve ~200 tokens for system template wrapper
        available_budget = max(token_budget - 200, 100)
        selected_records = self.solve_bounded_knapsack(scored, available_budget)

        # 5. Format prompt package P_B
        context_blocks: list[str] = []
        total_tokens = 0

        for r in selected_records:
            dt_str = datetime.datetime.fromtimestamp(r.timestamp).strftime("%H:%M:%S")
            block = (
                f"[{dt_str} | App: {r.app_name or 'Unknown'} | Window: {r.window_title or 'Untitled'}]\n"
                f"{r.redacted_text}"
            )
            context_blocks.append(block)
            total_tokens += max(r.token_count, 1)

        context_str = "\n\n".join(context_blocks) if context_blocks else "[No relevant recent activity found.]"
        prompt_text = self.SYSTEM_PROMPT_TEMPLATE.format(
            context_logs=context_str,
            query=query,
        )

        return PromptPackage(
            prompt_text=prompt_text,
            query=query,
            records=selected_records,
            total_tokens=total_tokens,
            token_budget=token_budget,
            assembled_at=t_now,
        )
