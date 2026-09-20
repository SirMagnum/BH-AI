"""
The three platform interfaces (PROJECT_CONTEXT §6a). This module defines
shapes only — no OS-specific code belongs here. Windows and macOS each
get one implementation per interface, selected at runtime by
`bhai.platform.select`; everything above this layer is platform-neutral
by construction, and `tests/test_platform_isolation.py` is the CI gate
that keeps it that way.

`CaptureSource` is the first of the three to get a real implementation
(Phase 2). `PerceptionBackend` and `OverlaySurface` are Phase 3 and 7.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorInfo:
    """One physical/logical monitor, in the coordinate space the backend
    natively reports. `scale_factor` is the DPI/Retina scale — Windows
    reports 1.0/1.25/1.5/2.0 for 100/125/150/200%, macOS Retina reports
    2.0. Callers must not assume either convention; convert explicitly.
    """

    id: str
    left: int
    top: int
    width: int
    height: int
    scale_factor: float


@dataclass
class RawFrame:
    """A captured frame BEFORE redaction.

    This type must never cross the capture-worker process boundary while
    unredacted — invariant 2. Redaction happens inside `acquire()` in the
    capture worker's own process, on this exact object, before it is
    written to the shared-memory ring buffer as a `RedactedFrame`.
    """

    rgb: bytes  # tightly packed, width*height*3 bytes, no padding
    width: int
    height: int
    monitor_id: str
    ts: float


class CaptureSource(ABC):
    """One implementation per platform, plus a portable fallback (`mss`).

    A backend owns nothing beyond a single capture session's resources —
    it is instantiated inside the capture worker process, used for that
    process's entire lifetime, and `close()`d when the process is told to
    stop. It has no knowledge of session state; the worker's lifetime
    encodes that (bhai/session/manager.py `_reconcile_capture`).
    """

    @abstractmethod
    def list_monitors(self) -> list[MonitorInfo]: ...

    @abstractmethod
    def grab(self, monitor_id: str) -> RawFrame:
        """Capture one frame from the given monitor. Must be safe to call
        repeatedly at whatever cadence the trigger policy decides — no
        internal state that degrades across calls."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any OS capture handle. Must make PAUSE's OS-level
        effect (invariant 1) true for THIS backend specifically — e.g.
        actually stop the `SCStream`/duplication interface, not just stop
        calling grab()."""
        ...
