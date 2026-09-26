"""
Unit tests for the SQLite episodic memory store (src/memory/db.py).
"""

import threading
import time
import unittest
from src.memory.db import (
    MemoryDatabase,
    SessionRecord,
    ActivityRecord,
    serialize_embedding,
    deserialize_embedding,
)


class TestMemoryDB(unittest.TestCase):

    def setUp(self):
        # Use ephemeral in-memory database for fast isolated tests
        self.db = MemoryDatabase(db_path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_embedding_serialization(self):
        vector = [0.123456, -0.987654, 0.0, 1.5]
        blob = serialize_embedding(vector)
        self.assertIsInstance(blob, bytes)
        self.assertEqual(len(blob), len(vector) * 4)

        restored = deserialize_embedding(blob)
        self.assertEqual(len(restored), len(vector))
        for original, deserialized in zip(vector, restored):
            self.assertAlmostEqual(original, deserialized, places=5)

        # Null / empty handling
        self.assertIsNone(serialize_embedding(None))
        self.assertIsNone(serialize_embedding([]))
        self.assertIsNone(deserialize_embedding(None))
        self.assertIsNone(deserialize_embedding(b""))

    def test_session_lifecycle(self):
        # Start session
        session = self.db.start_session("test-session-1")
        self.assertEqual(session.session_id, "test-session-1")
        self.assertIsNone(session.end_time)
        self.assertEqual(session.record_count, 0)

        # Active session query
        active = self.db.get_active_session()
        self.assertIsNotNone(active)
        self.assertEqual(active.session_id, "test-session-1")

        # End session
        self.db.end_session("test-session-1", summary="Worked on code review.")
        ended = self.db.get_session("test-session-1")
        self.assertIsNotNone(ended.end_time)
        self.assertEqual(ended.summary, "Worked on code review.")

        # Active session should now be None
        self.assertIsNone(self.db.get_active_session())

    def test_activity_records_crud(self):
        session = self.db.start_session("sess-100")
        embedding = [0.1, 0.2, 0.3, 0.4]

        # Add records
        rec1 = self.db.add_record(
            session_id=session.session_id,
            redacted_text="Opening document in editor.",
            app_name="Code.exe",
            window_title="main.py - Visual Studio Code",
            is_active=True,
            embedding=embedding,
            timestamp=1000.0,
        )
        self.assertEqual(rec1.redacted_text, "Opening document in editor.")
        self.assertEqual(rec1.embedding, embedding)
        self.assertTrue(rec1.is_active_window)

        rec2 = self.db.add_record(
            session_id=session.session_id,
            redacted_text="Searching for Python docs.",
            app_name="Chrome.exe",
            window_title="Python Documentation",
            is_active=False,
            timestamp=1005.0,
        )

        # Check session record counter was incremented
        updated_session = self.db.get_session("sess-100")
        self.assertEqual(updated_session.record_count, 2)

        # Retrieve records by session
        records = self.db.get_session_records("sess-100")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].record_id, rec1.record_id)
        self.assertEqual(records[1].record_id, rec2.record_id)

        # Retrieve records by timerange
        ranged = self.db.get_records_in_timerange(999.0, 1002.0)
        self.assertEqual(len(ranged), 1)
        self.assertEqual(ranged[0].record_id, rec1.record_id)

        # Update embedding
        new_emb = [0.9, 0.8, 0.7, 0.6]
        self.db.update_record_embedding(rec2.record_id, new_emb)
        updated_rec2 = self.db.get_session_records("sess-100")[1]
        for a, b in zip(updated_rec2.embedding, new_emb):
            self.assertAlmostEqual(a, b, places=5)

    def test_cascading_delete(self):
        session = self.db.start_session("sess-delete")
        self.db.add_record(session_id="sess-delete", redacted_text="Text 1")
        self.db.add_record(session_id="sess-delete", redacted_text="Text 2")

        self.assertEqual(len(self.db.get_session_records("sess-delete")), 2)

        # Delete session
        deleted = self.db.delete_session("sess-delete")
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_session("sess-delete"))

        # Associated records should be cascade-deleted
        self.assertEqual(len(self.db.get_session_records("sess-delete")), 0)

    def test_concurrent_writes(self):
        session = self.db.start_session("sess-threads")
        num_threads = 5
        records_per_thread = 20

        def worker(thread_idx):
            for i in range(records_per_thread):
                self.db.add_record(
                    session_id="sess-threads",
                    redacted_text=f"Thread {thread_idx} entry {i}",
                    app_name="worker.exe",
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = self.db.get_session_records("sess-threads", limit=1000)
        self.assertEqual(len(records), num_threads * records_per_thread)


if __name__ == "__main__":
    unittest.main()
