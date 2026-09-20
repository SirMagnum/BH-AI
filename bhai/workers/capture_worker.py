"""
Capture worker — Phase 2: real capture, real allowlist-based redaction,
real change scoring, real shared-memory ring. Still no perception
(Phase 3) and no OS focus-change hooks (§2.2 Tier 0) — this worker runs
on the adaptive interval alone (Tier 1/2) for now.

This process is the ONLY thing in the whole system that ever holds an
unredacted frame — and it holds one for exactly as long as it takes to
call `apply_watch_regions()`. The unredacted `RawFrame` is a local
variable, never returned from this module, never written anywhere, and
explicitly `del`eted the moment redaction produces its replacement.
This is invariant 2 made literal rather than asserted in a docstring.

`watch_regions` is an ALLOWLIST: with none configured, every frame comes
back fully black. See `bhai/capture/watch_regions.py` for why this is
the safer default than a denylist.

`result_queue` carries `FrameDescriptor`s only — shm name + slot index +
metadata, never pixels (roadmap §2.2: "never serialize image bytes").
"""

from __future__ import annotations

import queue as queue_module
from typing import Any

from bhai.capture.change import change_score, dhash_region
from bhai.capture.ring import FrameDescriptor, FrameRing
from bhai.capture.trigger import TriggerPolicy
from bhai.capture.watch_regions import WatchRegion, apply_watch_regions
from bhai.platform.interfaces import CaptureSource
from bhai.platform.portable.capture_mss import MssCaptureSource


def _monitor_still_matches(
    source: CaptureSource, monitor_id: str, expected_width: int, expected_height: int
) -> bool:
    """Fail-closed check (roadmap §2.4): if the monitor this worker was
    started for has changed size or vanished — unplugged, resolution
    changed, display sleep/wake reshuffling IDs — this must return False
    so the caller stops rather than silently redacting the wrong area of
    a differently-shaped screen, or writing a mismatched frame into a
    ring buffer sized for the old resolution.

    Pure function, no I/O beyond `source.list_monitors()`, specifically
    so it's unit-testable against a fake CaptureSource without needing a
    real display or a real resolution change.
    """
    for info in source.list_monitors():
        if info.id == monitor_id:
            return info.width == expected_width and info.height == expected_height
    return False  # the monitor is gone entirely


def run(
    stop_event: Any,  # multiprocessing.Event
    result_queue: Any,  # multiprocessing.Queue[FrameDescriptor]
    monitor_id: str = "1",
    watch_regions: list[WatchRegion] | None = None,
) -> None:
    watch_regions = watch_regions or []  # empty -> every frame comes back fully black
    source = MssCaptureSource()
    ring: FrameRing | None = None
    trigger = TriggerPolicy()
    prev_hash: int | None = None

    try:
        while not stop_event.is_set():
            raw = source.grab(monitor_id)  # UNREDACTED — local only, never escapes this scope
            redacted = apply_watch_regions(raw, watch_regions)
            del raw  # gone: not returned, not stored, not reachable after this line

            if ring is None:
                ring = FrameRing(redacted.width, redacted.height, create=True)
            elif not _monitor_still_matches(source, monitor_id, ring.width, ring.height):
                # Fail closed: stop capturing entirely rather than write a
                # mismatched frame. The main process's watch loop treats
                # this exit exactly like a crash — session -> PAUSED,
                # user notified, never a silent respawn (§2.4, invariant 1).
                break

            # Hash just the watched area, not the whole (mostly
            # guaranteed-black) frame — see change.py's module docstring
            # for the bug this fixes: a small watch region's real changes
            # were getting diluted away by dHash's coarse full-frame
            # downsample, wrongly backing the trigger off to its slowest
            # interval while content inside the watched area was actively
            # changing.
            new_hash = dhash_region(redacted, watch_regions)
            score = 0.0 if prev_hash is None else change_score(prev_hash, new_hash)
            prev_hash = new_hash
            trigger.on_change_score(score)

            slot = ring.write(redacted.rgb)
            descriptor = FrameDescriptor(
                shm_name=ring.name,
                slot=slot,
                width=redacted.width,
                height=redacted.height,
                monitor_id=monitor_id,
                frame_ts=redacted.ts,
                change_score=score,
            )
            try:
                result_queue.put_nowait(descriptor)
            except queue_module.Full:
                pass  # drop-oldest lives on the consumer side; never block capture on a full queue

            stop_event.wait(timeout=trigger.interval)
    finally:
        source.close()
        if ring is not None:
            ring.unlink()
