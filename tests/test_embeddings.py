"""
Unit tests for the Local Dense Vector Embedding Engine (src/memory/embeddings.py).
"""

import math
import unittest
import numpy as np

from src.memory.embeddings import (
    EmbeddingEngine,
    EmbeddingBackend,
    cosine_similarity,
)


class TestEmbeddings(unittest.TestCase):

    def test_cosine_similarity(self):
        # Identical vectors
        u = [1.0, 0.0, 0.0]
        v = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(u, v), 1.0, places=5)

        # Orthogonal vectors
        w = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(u, w), 0.0, places=5)

        # Opposite vectors
        opp = [-1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(u, opp), -1.0, places=5)

        # Empty / None
        self.assertEqual(cosine_similarity([], [1.0]), 0.0)
        self.assertEqual(cosine_similarity(None, [1.0]), 0.0)

    def test_tfidf_semantic_embedding(self):
        engine = EmbeddingEngine(dimension=128, backend=EmbeddingBackend.TFIDF_SEMANTIC)
        self.assertEqual(engine.backend_name, EmbeddingBackend.TFIDF_SEMANTIC.value)
        self.assertEqual(engine.dimension, 128)

        text_a = "Writing Python code and unit tests."
        text_b = "Executing Python code test scripts."
        text_c = "Delicious banana chocolate ice cream dessert recipe."

        vec_a = engine.embed_text(text_a)
        vec_b = engine.embed_text(text_b)
        vec_c = engine.embed_text(text_c)

        # Verify dimension
        self.assertEqual(len(vec_a), 128)
        self.assertEqual(len(vec_b), 128)
        self.assertEqual(len(vec_c), 128)

        # Verify L2 normalization (||e|| == 1.0)
        norm_a = np.linalg.norm(vec_a)
        self.assertAlmostEqual(norm_a, 1.0, places=4)

        # Verify semantic relevance: (a, b) should be significantly higher than (a, c)
        sim_ab = cosine_similarity(vec_a, vec_b)
        sim_ac = cosine_similarity(vec_a, vec_c)
        self.assertGreater(sim_ab, sim_ac)
        self.assertGreater(sim_ab, 0.3)  # Overlapping subwords/words

    def test_batch_embedding(self):
        engine = EmbeddingEngine(dimension=64, backend=EmbeddingBackend.TFIDF_SEMANTIC)
        texts = ["First line of text", "Second line of text"]

        batch_vecs = engine.embed_batch(texts)
        self.assertEqual(len(batch_vecs), 2)

        single_0 = engine.embed_text(texts[0])
        single_1 = engine.embed_text(texts[1])

        # Batch outputs should match single outputs
        for a, b in zip(batch_vecs[0], single_0):
            self.assertAlmostEqual(a, b, places=5)
        for a, b in zip(batch_vecs[1], single_1):
            self.assertAlmostEqual(a, b, places=5)

    def test_empty_text_handling(self):
        engine = EmbeddingEngine(dimension=64, backend=EmbeddingBackend.TFIDF_SEMANTIC)
        empty_vec = engine.embed_text("")
        self.assertEqual(empty_vec, [0.0] * 64)

        ws_vec = engine.embed_text("   \n\t  ")
        self.assertEqual(ws_vec, [0.0] * 64)

    def test_mock_backend(self):
        engine = EmbeddingEngine(dimension=64, backend=EmbeddingBackend.MOCK)
        self.assertEqual(engine.backend_name, EmbeddingBackend.MOCK.value)

        vec1 = engine.embed_text("Sample input")
        vec2 = engine.embed_text("Sample input")

        # Deterministic
        self.assertEqual(vec1, vec2)
        norm = np.linalg.norm(vec1)
        self.assertAlmostEqual(norm, 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
