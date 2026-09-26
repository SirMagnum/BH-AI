"""
Unit tests for the Episodic RAG Engine (src/memory/rag.py).
"""

import math
import unittest

from src.memory.db import MemoryDatabase, ActivityRecord
from src.memory.embeddings import EmbeddingEngine, EmbeddingBackend
from src.memory.rag import (
    EpisodicRAGEngine,
    PromptPackage,
    ScoredRecord,
    compute_relevance_score,
)


class TestRAG(unittest.TestCase):

    def setUp(self):
        self.db = MemoryDatabase(":memory:")
        self.embeddings = EmbeddingEngine(dimension=64, backend=EmbeddingBackend.TFIDF_SEMANTIC)
        self.rag = EpisodicRAGEngine(
            db=self.db,
            embeddings=self.embeddings,
            alpha=0.7,
            lambda_decay=0.001,
        )

    def tearDown(self):
        self.db.close()

    def test_relevance_scoring_formula(self):
        # Exact mathematical test:
        # e_r = [1, 0], e_q = [1, 0] -> cos_sim = 1.0
        # active = True -> I_active = 1.0
        # alpha = 0.7 -> context = 0.7(1.0) + 0.3(1.0) = 1.0
        # delta_t = 100s -> decay = exp(-0.001 * 100) = exp(-0.1) ≈ 0.904837
        score, cos_sim, decay = compute_relevance_score(
            record_embedding=[1.0, 0.0],
            query_embedding=[1.0, 0.0],
            is_active_window=True,
            timestamp=1000.0,
            current_time=1100.0,
            alpha=0.7,
            lambda_decay=0.001,
        )

        self.assertAlmostEqual(cos_sim, 1.0, places=4)
        self.assertAlmostEqual(decay, math.exp(-0.1), places=4)
        self.assertAlmostEqual(score, 1.0 * math.exp(-0.1), places=4)

    def test_time_decay_impact(self):
        # A recent event vs an old event with identical content
        emb = [1.0, 0.0]
        recent_score, _, _ = compute_relevance_score(
            record_embedding=emb, query_embedding=emb,
            is_active_window=True, timestamp=1000.0, current_time=1010.0,
        )
        old_score, _, _ = compute_relevance_score(
            record_embedding=emb, query_embedding=emb,
            is_active_window=True, timestamp=1000.0, current_time=3000.0,
        )

        self.assertGreater(recent_score, old_score)

    def test_active_window_bias(self):
        emb = [1.0, 0.0]
        active_score, _, _ = compute_relevance_score(
            record_embedding=emb, query_embedding=emb,
            is_active_window=True, timestamp=1000.0, current_time=1000.0,
            alpha=0.6,
        )
        inactive_score, _, _ = compute_relevance_score(
            record_embedding=emb, query_embedding=emb,
            is_active_window=False, timestamp=1000.0, current_time=1000.0,
            alpha=0.6,
        )

        # Difference should be (1 - alpha) = 0.4
        self.assertAlmostEqual(active_score - inactive_score, 0.4, places=4)

    def test_bounded_knapsack_budget(self):
        # Create candidate records with different token weights
        records = [
            ActivityRecord(
                record_id="r1", session_id="s1", timestamp=10.0, app_name="App",
                window_title="Win", redacted_text="Short text", is_active_window=True, token_count=50
            ),
            ActivityRecord(
                record_id="r2", session_id="s1", timestamp=20.0, app_name="App",
                window_title="Win", redacted_text="Medium text", is_active_window=True, token_count=100
            ),
            ActivityRecord(
                record_id="r3", session_id="s1", timestamp=30.0, app_name="App",
                window_title="Win", redacted_text="Very long text", is_active_window=True, token_count=200
            ),
        ]

        scored = [
            ScoredRecord(record=records[0], score=0.9, cosine_sim=0.9, time_decay=1.0),
            ScoredRecord(record=records[1], score=0.8, cosine_sim=0.8, time_decay=1.0),
            ScoredRecord(record=records[2], score=0.5, cosine_sim=0.5, time_decay=1.0),
        ]

        # Budget of 120 tokens: r1 (cost 50) + r2 (cost 100) exceeds 120, so only r1 fits
        selected = self.rag.solve_bounded_knapsack(scored, token_budget=120)
        total_tokens = sum(r.token_count for r in selected)

        self.assertLessEqual(total_tokens, 120)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].record_id, "r1")

        # Budget of 160 tokens: r1 (cost 50) + r2 (cost 100) = 150 fits!
        selected_160 = self.rag.solve_bounded_knapsack(scored, token_budget=160)
        self.assertEqual(len(selected_160), 2)
        self.assertEqual(selected_160[0].record_id, "r1")
        self.assertEqual(selected_160[1].record_id, "r2")

    def test_retrieve_and_assemble_pipeline(self):
        session = self.db.start_session("rag-session")

        # Insert records into memory database
        self.db.add_record(
            session_id=session.session_id,
            redacted_text="Configuring Python virtual environment with venv and pip.",
            app_name="Terminal",
            window_title="PowerShell",
            is_active=True,
            token_count=15,
        )
        self.db.add_record(
            session_id=session.session_id,
            redacted_text="Editing Python state machine unit tests in VS Code.",
            app_name="Code.exe",
            window_title="test_state_machine.py",
            is_active=True,
            token_count=20,
        )
        self.db.add_record(
            session_id=session.session_id,
            redacted_text="Reading cooking recipe for Italian pasta bolognese.",
            app_name="Chrome.exe",
            window_title="Recipe Website",
            is_active=False,
            token_count=18,
        )

        # Run RAG query
        pkg = self.rag.retrieve_and_assemble(
            query="What Python tests did I work on?",
            session_id=session.session_id,
            token_budget=500,
        )

        self.assertIsInstance(pkg, PromptPackage)
        self.assertEqual(pkg.query, "What Python tests did I work on?")
        self.assertGreater(len(pkg.records), 0)
        self.assertLessEqual(pkg.total_tokens, 500)

        # Prompt should contain the observation logs
        self.assertIn("OBSERVATION CONTEXT", pkg.prompt_text)
        self.assertIn("Python", pkg.prompt_text)
        self.assertIn("User Request: What Python tests did I work on?", pkg.prompt_text)


if __name__ == "__main__":
    unittest.main()
