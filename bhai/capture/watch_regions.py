"""
Watch regions — an ALLOWLIST, not a denylist. Replaces the earlier
"blocked regions" model (roadmap §2.4 as originally written) with a
stronger default: the capture worker sees NOTHING unless a region has
been explicitly marked watchable. Applied INSIDE the capture worker
process, before the frame is written to shared memory — same invariant-2
placement as before, just a different rule about what survives.

Why the flip: a denylist's safety depends entirely on the user
remembering to block every sensitive area, and a screen full of
password fields, chat windows, or other people's names is only as
private as the last thing you forgot to block. An allowlist's default
state — before you've configured anything at all — is a fully black
frame. That is strictly safer, and it is a direct, literal reading of
PROJECT_CONTEXT's own thesis: "the assistant cannot see the screen at
all until a session is started." This extends that same idea one level
further — it cannot see any AREA of the screen until you've said it can.

Coordinates are normalized [0, 1] relative to the source monitor, same
as before. A resolution change still fails closed via
`workers/capture_worker.py`'s `_monitor_still_matches` — that check is
unaffected by this flip.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bhai.platform.interfaces import RawFrame


@dataclass(frozen=True)
class WatchRegion:
    """Normalized [0, 1] coordinates relative to the source monitor —
    the area the AI IS allowed to see. Everything outside every
    WatchRegion is blacked out; if there are none at all, the entire
    frame is blacked out."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        for name, val in (("x", self.x), ("y", self.y), ("w", self.w), ("h", self.h)):
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"WatchRegion.{name} must be in [0, 1], got {val}")


def apply_watch_regions(frame: RawFrame, regions: list[WatchRegion]) -> RawFrame:
    """Return a NEW RawFrame that is black everywhere EXCEPT inside the
    given regions.

    No regions at all -> the entire frame comes back black. This is the
    safe-by-default path and it is exercised on every session until the
    user has drawn at least one watch region.
    """
    w, h = frame.width, frame.height
    source = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(h, w, 3)
    out = np.zeros_like(source)  # black canvas — nothing survives unless copied in below

    for region in regions:
        x1 = max(0, min(w, round(region.x * w)))
        y1 = max(0, min(h, round(region.y * h)))
        x2 = max(0, min(w, round((region.x + region.w) * w)))
        y2 = max(0, min(h, round((region.y + region.h) * h)))
        out[y1:y2, x1:x2, :] = source[y1:y2, x1:x2, :]

    return RawFrame(rgb=out.tobytes(), width=w, height=h, monitor_id=frame.monitor_id, ts=frame.ts)
