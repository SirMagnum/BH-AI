"""
SQLite 3-Tier Episodic Memory Store for BH-AI.
Persists sessions and sanitized OCR activity records with vector embedding blobs.
Configured with Write-Ahead Logging (WAL) and foreign key enforcement for high concurrency.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("BH-AI.MemoryDB")


# ------------------------------------------------------------------ #
#  Data Models
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class SessionRecord:
    """Represents an observation session."""
    session_id: str
    start_time: float
    end_time: float | None = None
    summary: str = ""
    record_count: int = 0


@dataclass(frozen=True)
class ActivityRecord:
    """Represents a sanitized OCR observation snapshot."""
    record_id: str
    session_id: str
    timestamp: float
    app_name: str
    window_title: str
    redacted_text: str
    is_active_window: bool
    embedding: list[float] | None = None
    token_count: int = 0


# ------------------------------------------------------------------ #
#  Vector Serialization Helpers
# ------------------------------------------------------------------ #

def serialize_embedding(vector: list[float] | None) -> bytes | None:
    """Pack a float vector into binary bytes using single-precision IEEE 754."""
    if vector is None or len(vector) == 0:
        return None
    return struct.pack(f"{len(vector)}f", *vector)


def deserialize_embedding(blob: bytes | None) -> list[float] | None:
    """Unpack binary float blob into a list of floats."""
    if blob is None or len(blob) == 0:
        return None
    num_floats = len(blob) // 4
    return list(struct.unpack(f"{num_floats}f", blob))


# ------------------------------------------------------------------ #
#  Database Manager
# ------------------------------------------------------------------ #

class MemoryDatabase:
    """
    Thread-safe SQLite storage engine for episodic sessions and activity records.
    """

    def __init__(self, db_path: str = "data/bhai_memory.db"):
        self.db_path = db_path
        self._lock = threading.RLock()

        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema, pragmas, and indexes."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON;")
            if self.db_path != ":memory:":
                cur.execute("PRAGMA journal_mode = WAL;")
                cur.execute("PRAGMA synchronous = NORMAL;")

            # Sessions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    summary TEXT DEFAULT '',
                    record_count INTEGER DEFAULT 0
                );
            """)

            # Activity records table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_records (
                    record_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    app_name TEXT DEFAULT '',
                    window_title TEXT DEFAULT '',
                    redacted_text TEXT NOT NULL,
                    is_active_window INTEGER DEFAULT 1,
                    embedding_blob BLOB,
                    token_count INTEGER DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            # Fast search indices for session RAG and time-decay calculations
            cur.execute("CREATE INDEX IF NOT EXISTS idx_records_session ON activity_records(session_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_records_time ON activity_records(timestamp);")
            self._conn.commit()

    # ------------------------------------------------------------------ #
    #  Session Lifecycle APIs
    # ------------------------------------------------------------------ #

    def start_session(self, session_id: str | None = None) -> SessionRecord:
        """Create a new observation session."""
        sid = session_id or str(uuid.uuid4())
        start_t = time.time()

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO sessions (session_id, start_time, record_count) VALUES (?, ?, 0)",
                (sid, start_t),
            )
            self._conn.commit()

        return SessionRecord(session_id=sid, start_time=start_t, record_count=0)

    def end_session(self, session_id: str, summary: str = "") -> None:
        """Mark an observation session as closed with an optional summary."""
        end_t = time.time()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE sessions SET end_time = ?, summary = ? WHERE session_id = ?",
                (end_t, summary, session_id),
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Retrieve a specific session by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if not row:
                return None
            return SessionRecord(
                session_id=row["session_id"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                summary=row["summary"] or "",
                record_count=row["record_count"],
            )

    def get_active_session(self) -> SessionRecord | None:
        """Retrieve the most recent unclosed session."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM sessions WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            return SessionRecord(
                session_id=row["session_id"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                summary=row["summary"] or "",
                record_count=row["record_count"],
            )

    def list_sessions(self, limit: int = 50) -> list[SessionRecord]:
        """List recent sessions."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ?", (limit,)
            )
            rows = cur.fetchall()
            return [
                SessionRecord(
                    session_id=r["session_id"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                    summary=r["summary"] or "",
                    record_count=r["record_count"],
                )
                for r in rows
            ]

    def delete_session(self, session_id: str) -> bool:
        """Delete session and all its associated records (cascade)."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    #  Activity Records APIs
    # ------------------------------------------------------------------ #

    def add_record(
        self,
        session_id: str,
        redacted_text: str,
        app_name: str = "",
        window_title: str = "",
        is_active: bool = True,
        embedding: list[float] | None = None,
        token_count: int | None = None,
        timestamp: float | None = None,
    ) -> ActivityRecord:
        """
        Store a sanitized OCR activity record into episodic memory.
        Increments parent session's record counter.
        """
        rec_id = str(uuid.uuid4())
        ts = timestamp if timestamp is not None else time.time()
        blob = serialize_embedding(embedding)

        # Approximate token count if not provided (roughly 1 token per 4 characters / 1 word)
        t_count = token_count if token_count is not None else max(len(redacted_text.split()), 1)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO activity_records (
                    record_id, session_id, timestamp, app_name, window_title,
                    redacted_text, is_active_window, embedding_blob, token_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec_id,
                    session_id,
                    ts,
                    app_name,
                    window_title,
                    redacted_text,
                    1 if is_active else 0,
                    blob,
                    t_count,
                ),
            )
            cur.execute(
                "UPDATE sessions SET record_count = record_count + 1 WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()

        return ActivityRecord(
            record_id=rec_id,
            session_id=session_id,
            timestamp=ts,
            app_name=app_name,
            window_title=window_title,
            redacted_text=redacted_text,
            is_active_window=is_active,
            embedding=embedding,
            token_count=t_count,
        )

    def get_session_records(self, session_id: str, limit: int = 500) -> list[ActivityRecord]:
        """Retrieve activity records for a given session."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT * FROM activity_records 
                WHERE session_id = ? 
                ORDER BY timestamp ASC 
                LIMIT ?
                """,
                (session_id, limit),
            )
            return [self._row_to_record(r) for r in cur.fetchall()]

    def get_recent_records(self, limit: int = 100) -> list[ActivityRecord]:
        """Retrieve recent activity records across sessions."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM activity_records ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            return [self._row_to_record(r) for r in cur.fetchall()]

    def get_records_in_timerange(self, start_time: float, end_time: float) -> list[ActivityRecord]:
        """Retrieve activity records within a timestamp range."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT * FROM activity_records 
                WHERE timestamp >= ? AND timestamp <= ? 
                ORDER BY timestamp ASC
                """,
                (start_time, end_time),
            )
            return [self._row_to_record(r) for r in cur.fetchall()]

    def update_record_embedding(self, record_id: str, embedding: list[float]) -> None:
        """Update the dense vector embedding for a stored activity record."""
        blob = serialize_embedding(embedding)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE activity_records SET embedding_blob = ? WHERE record_id = ?",
                (blob, record_id),
            )
            self._conn.commit()

    def update_session_summary(self, session_id: str, summary: str) -> None:
        """Update session summary."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?",
                (summary, session_id),
            )
            self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> ActivityRecord:
        """Map SQLite row to ActivityRecord dataclass."""
        return ActivityRecord(
            record_id=row["record_id"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            app_name=row["app_name"],
            window_title=row["window_title"],
            redacted_text=row["redacted_text"],
            is_active_window=bool(row["is_active_window"]),
            embedding=deserialize_embedding(row["embedding_blob"]),
            token_count=row["token_count"],
        )

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
