"""
RegionStore — watch-region persistence (roadmap §2.4, allowlist model).

Deliberately GLOBAL, not session-scoped: watch regions are a privacy
*configuration* ("the AI may see inside this area"), not session data.
That is why `watch_regions` is excluded from `SessionStore.discard_session`'s
atomic delete — ending or discarding a session must never touch what the
user has told the app it's allowed to look at.

Regions are keyed by a "monitor signature" (currently just
`f"{width}x{height}"`) rather than reused blindly across resolutions. A
lookup for a resolution with no saved regions returns an empty list —
which, per `bhai.capture.watch_regions.apply_watch_regions`, means the
capture worker sees nothing at all for that resolution. That is the
fail-safe default, not a bug. Real per-monitor identity (stable across
cable/dock changes) is a Phase 2 stretch item once a real Windows
backend can report it.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from bhai.capture.watch_regions import WatchRegion
from bhai.db.schema import DDL


class RegionStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Idempotent: safe whether SessionStore already ran this or not,
        # and safe to construct a RegionStore before any session exists.
        self._conn.executescript(DDL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def signature(width: int, height: int) -> str:
        return f"{width}x{height}"

    def add(self, monitor_signature: str, region: WatchRegion) -> None:
        self._conn.execute(
            "INSERT INTO watch_regions (monitor_signature, x, y, w, h, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (monitor_signature, region.x, region.y, region.w, region.h, time.time()),
        )
        self._conn.commit()

    def list_for(self, monitor_signature: str) -> list[WatchRegion]:
        rows = self._conn.execute(
            "SELECT x, y, w, h FROM watch_regions WHERE monitor_signature = ?",
            (monitor_signature,),
        ).fetchall()
        return [WatchRegion(x=r[0], y=r[1], w=r[2], h=r[3]) for r in rows]

    def clear(self, monitor_signature: str) -> None:
        self._conn.execute(
            "DELETE FROM watch_regions WHERE monitor_signature = ?", (monitor_signature,)
        )
        self._conn.commit()
