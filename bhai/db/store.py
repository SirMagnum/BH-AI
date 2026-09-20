"""
SessionStore — the only module that touches sqlite3 directly.

WAL mode + foreign keys on. `discard_session` is the load-bearing method:
it must delete every row for a `session_id` in one transaction, because
"ending a session without saving leaves zero rows for that session_id" is
a Phase 1 Definition-of-Done item, not an aspiration.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from bhai.db.schema import DDL, SCHEMA_VERSION
from bhai.session.states import SessionState

APP_VERSION = "0.1.0"


class SessionStore:
    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(DDL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ #
    #  Session lifecycle
    # ------------------------------------------------------------------ #

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO sessions "
            "(id, started_at, state, save_requested, app_version, schema_version) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (session_id, time.time(), SessionState.IDLE.value, APP_VERSION, SCHEMA_VERSION),
        )
        self._conn.commit()
        return session_id

    def update_state(self, session_id: str, state: SessionState) -> None:
        self._conn.execute("UPDATE sessions SET state=? WHERE id=?", (state.value, session_id))
        self._conn.commit()

    def record_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict,
        correlation_id: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO events (session_id, ts, type, payload_json, correlation_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, time.time(), event_type, json.dumps(payload), correlation_id),
        )
        self._conn.commit()

    def mark_saved(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET state=?, ended_at=?, save_requested=1 WHERE id=?",
            (SessionState.SAVED.value, time.time(), session_id),
        )
        self._conn.commit()

    def discard_session(self, session_id: str) -> None:
        """Delete every row for this session_id in ONE transaction (invariant 4).

        `with self._conn:` commits on success and rolls back on exception —
        sqlite3's implicit-transaction behaviour makes these two DELETEs
        atomic without an explicit BEGIN.
        """
        with self._conn:
            self._conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def row_count_for_session(self, session_id: str) -> int:
        """Test helper: total rows across every session-scoped table for this id."""
        n = self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id=?", (session_id,)
        ).fetchone()[0]
        n += self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        return n

    def vacuum(self) -> None:
        """Reclaim space after discards. Not called per-session (roadmap
        says the DB 'is VACUUMed' on end, but VACUUM rewrites the whole
        file — expensive per session in a real app). Called on app close
        or periodically instead; a Phase 4 concern to schedule properly.
        """
        self._conn.execute("VACUUM")
