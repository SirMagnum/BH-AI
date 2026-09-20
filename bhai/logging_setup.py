"""
Structured logging (roadmap §2.10).

- JSON lines to stdout (a session-scoped rotating file is a later phase).
- `correlation_id` threads through via a contextvar so a user turn can be
  followed across the bus, workers, and any future LLM/provider call.
- Content-level redaction is STRUCTURAL here, not a discipline we hope
  callers follow: every call site passes structured fields (session_id,
  pid, event names), and nothing in this module accepts a free-text blob
  that could be captured-screen content or a user utterance. A future
  TRACE level for content-bearing debug logs must be compiled out of
  release builds — not implemented yet, tracked in docs/degradation.md.
"""

from __future__ import annotations

import contextvars
import logging
import sys

import structlog

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(cid: str | None) -> None:
    _correlation_id.set(cid)


def _add_correlation_id(logger, method_name, event_dict):  # noqa: ARG001
    cid = _correlation_id.get()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            _add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
