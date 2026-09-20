"""
Typed events on the internal event bus (roadmap §2.8).

Every event carries `session_id` where one applies (invariant 4) and a
`correlation_id` so a user turn can be threaded through logs end to end.
Payloads never carry captured content (redacted frames, OCR text, user
utterances) at this layer's default — see bhai/logging_setup.py for the
matching log-redaction rule. This module is the schema; nothing here reads
or writes it, so it is safe to import from anywhere without pulling in Qt,
sqlite, or multiprocessing.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from bhai.session.states import SessionState


def _event_id() -> str:
    return uuid.uuid4().hex


def _now() -> float:
    return time.time()


class BusEvent(BaseModel):
    """Base class for everything published on the bus."""

    event_id: str = Field(default_factory=_event_id)
    ts: float = Field(default_factory=_now)
    correlation_id: str | None = None

    # A dotted topic used for subscription filtering, e.g. "session.state_changed".
    topic: str = "event"


class SessionStateChanged(BusEvent):
    topic: Literal["session.state_changed"] = "session.state_changed"
    session_id: str
    old_state: SessionState
    new_state: SessionState
    reason: str = ""


class CaptureWorkerStarted(BusEvent):
    topic: Literal["capture.worker_started"] = "capture.worker_started"
    session_id: str
    pid: int


class CaptureWorkerStopped(BusEvent):
    topic: Literal["capture.worker_stopped"] = "capture.worker_stopped"
    session_id: str
    pid: int
    expected: bool  # False => this is what drives WORKER_CRASHED


class CaptureFrameAvailable(BusEvent):
    """A frame is ready in the shared-memory ring. Carries a locator, not
    pixels — consumers (the trust inspector, later perception) attach to
    `shm_name` and read `slot` themselves. This topic is drop-oldest
    (bhai.bus.bus._DROP_OLDEST_TOPICS): a stale frame notification is
    actively misleading, never just late.
    """

    topic: Literal["capture.frame"] = "capture.frame"
    session_id: str
    shm_name: str
    slot: int
    width: int
    height: int
    monitor_id: str
    frame_ts: float
    change_score: float


class ComputeWorkerStarted(BusEvent):
    topic: Literal["compute.worker_started"] = "compute.worker_started"
    pid: int


class ComputeWorkerStopped(BusEvent):
    topic: Literal["compute.worker_stopped"] = "compute.worker_stopped"
    pid: int
    expected: bool
    restart_count: int = 0


class LogEvent(BusEvent):
    """Mirrors a structlog record onto the bus for the dev "event log" panel.

    Content-redaction rule applies here too: `message` must never contain
    captured screen content or user utterances. Enforced in logging_setup.
    """

    topic: Literal["log"] = "log"
    level: str
    message: str
    logger_name: str = ""


class ErrorEvent(BusEvent):
    topic: Literal["error"] = "error"
    session_id: str | None = None
    category: Literal["user_recoverable", "degradable", "fatal"]
    message: str
