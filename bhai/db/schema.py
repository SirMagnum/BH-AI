"""
SQLite schema v1 — session skeleton (roadmap "Database schema evolution").

Every session-scoped table carries `session_id`; deleting a session is one
atomic transaction across all of them (invariant 4). `events` is the
append-only source of truth (invariant 5) — later phases derive
observations/summaries/embeddings from it and can always re-derive.

`settings` and `watch_regions` are NOT session-scoped by design:
settings are global app config, and watch regions are a persistent
privacy configuration that must survive across sessions (roadmap §2.4 —
"persisted globally, not per session").

`watch_regions` is an ALLOWLIST ("the AI can see inside this rectangle"),
not a denylist — see `bhai/capture/watch_regions.py` for why. No rows for
a given monitor signature means the capture worker sees nothing at all
for that resolution, which is the safe default.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    state           TEXT NOT NULL,
    save_requested  INTEGER NOT NULL DEFAULT 0,
    app_version     TEXT NOT NULL,
    schema_version  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    ts              REAL NOT NULL,
    type            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    correlation_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_session_ts   ON events(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_session_type ON events(session_id, type);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_regions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_signature  TEXT NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
    created_at REAL NOT NULL
);
"""
