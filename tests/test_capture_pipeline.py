"""
Unit tests for the watch-region allowlist, change scoring, and the
shared-memory ring — the platform-neutral core of Phase 2 (roadmap
§2.2/§2.4).

`test_default_is_no_watch_regions_yields_fully_black_frame` and
`test_content_outside_watch_region_is_blacked_out` are the load-bearing
tests here: they prove the allowlist model's central claim — nothing is
visible unless explicitly allowed, and a "secret" placed outside every
watch region never survives.
"""

from __future__ import annotations

import numpy as np
import pytest

from bhai.capture.change import change_score, dhash, hamming_distance
from bhai.capture.ring import RING_SIZE, FrameRing
from bhai.capture.watch_regions import WatchRegion, apply_watch_regions
from bhai.platform.interfaces import RawFrame


def _solid_frame(width: int, height: int, rgb_value: tuple[int, int, int]) -> RawFrame:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :] = rgb_value
    return RawFrame(rgb=arr.tobytes(), width=width, height=height, monitor_id="1", ts=0.0)


def _frame_with_marker(width: int, height: int, marker_box: tuple[int, int, int, int]) -> RawFrame:
    """A frame that is black everywhere except a bright white 'secret' box
    at the given (x1, y1, x2, y2) pixel coordinates."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = marker_box
    arr[y1:y2, x1:x2, :] = 255
    return RawFrame(rgb=arr.tobytes(), width=width, height=height, monitor_id="1", ts=0.0)


# ---------------------------------------------------------------------- #
#  Watch regions — the allowlist model's adversarial tests
# ---------------------------------------------------------------------- #


def test_default_is_no_watch_regions_yields_fully_black_frame() -> None:
    """The safe-by-default claim: before anything has been selected, a
    real frame with real (non-black) content comes back entirely black."""
    frame = _solid_frame(100, 100, (200, 150, 100))  # definitely not black
    result = apply_watch_regions(frame, [])

    arr = np.frombuffer(result.rgb, dtype=np.uint8)
    assert arr.max() == 0, "expected a fully black frame with no watch regions configured"


def test_content_inside_watch_region_is_preserved() -> None:
    width, height = 100, 100
    frame = _solid_frame(width, height, (10, 20, 30))
    region = WatchRegion(x=0.0, y=0.0, w=0.2, h=0.2)  # only the top-left corner is watchable
    result = apply_watch_regions(frame, [region])

    arr = np.frombuffer(result.rgb, dtype=np.uint8).reshape(height, width, 3)
    assert tuple(arr[5, 5]) == (10, 20, 30)  # inside the watch region — preserved


def test_content_outside_watch_region_is_blacked_out() -> None:
    """The adversarial test: a 'secret' sitting OUTSIDE every watch
    region must never survive, no matter what else is selected."""
    width, height = 100, 100
    secret_box = (60, 60, 80, 80)  # the "secret" — deliberately outside the watch region below
    frame = _frame_with_marker(width, height, secret_box)

    watch_region = WatchRegion(x=0.0, y=0.0, w=0.3, h=0.3)  # top-left only; secret is bottom-right
    result = apply_watch_regions(frame, [watch_region])

    arr = np.frombuffer(result.rgb, dtype=np.uint8).reshape(height, width, 3)
    outside = arr.copy()
    outside[0:30, 0:30, :] = 0  # zero out the watch region itself, leaving only "outside"
    assert outside.max() == 0, "a secret outside the watch region leaked through"


def test_overlapping_watch_regions_are_all_preserved() -> None:
    width, height = 100, 100
    frame = _solid_frame(width, height, (5, 5, 5))
    regions = [WatchRegion(x=0.0, y=0.0, w=0.5, h=0.5), WatchRegion(x=0.4, y=0.4, w=0.5, h=0.5)]
    result = apply_watch_regions(frame, regions)

    arr = np.frombuffer(result.rgb, dtype=np.uint8).reshape(height, width, 3)
    assert tuple(arr[10, 10]) == (5, 5, 5)  # inside region 1 only
    assert tuple(arr[70, 70]) == (5, 5, 5)  # inside region 2 only
    assert tuple(arr[95, 95]) == (0, 0, 0)  # outside both


def test_watch_region_rejects_out_of_range_coordinates() -> None:
    with pytest.raises(ValueError):
        WatchRegion(x=1.5, y=0, w=0.1, h=0.1)


# ---------------------------------------------------------------------- #
#  Change detection
# ---------------------------------------------------------------------- #


def test_identical_frames_have_zero_change_score() -> None:
    frame = _solid_frame(64, 64, (50, 60, 70))
    h1 = dhash(frame)
    h2 = dhash(frame)
    assert hamming_distance(h1, h2) == 0
    assert change_score(h1, h2) == 0.0


def test_very_different_frames_have_high_change_score() -> None:
    # dHash encodes HORIZONTAL gradients only (each pixel vs. its right
    # neighbour) — a top/bottom split has zero horizontal gradient in
    # either frame and would wrongly look identical. Use a left/right
    # split so the difference is actually visible to the hash.
    black = _solid_frame(64, 64, (0, 0, 0))
    left_right_split = _frame_with_marker(64, 64, (0, 0, 32, 64))
    score = change_score(dhash(black), dhash(left_right_split))
    assert score > 0.1  # not identical — the exact number isn't the point


# ---------------------------------------------------------------------- #
#  Shared-memory ring
# ---------------------------------------------------------------------- #


def test_ring_round_trips_frame_bytes() -> None:
    ring = FrameRing(width=8, height=8, create=True)
    try:
        payload = bytes(range(8 * 8 * 3 % 256)) * ((8 * 8 * 3 // (8 * 8 * 3 % 256)) + 1)
        payload = payload[: 8 * 8 * 3]
        slot = ring.write(payload)
        assert ring.read(slot) == payload
    finally:
        ring.unlink()


def test_ring_wraps_after_ring_size_writes() -> None:
    ring = FrameRing(width=2, height=2, create=True)
    try:
        slots = []
        for i in range(RING_SIZE + 3):
            payload = bytes([i % 256]) * (2 * 2 * 3)
            slots.append(ring.write(payload))
        assert slots[-1] == 2  # wrapped: (RING_SIZE + 3 - 1) % RING_SIZE == 2
    finally:
        ring.unlink()


def test_ring_rejects_mismatched_frame_size() -> None:
    ring = FrameRing(width=4, height=4, create=True)
    try:
        with pytest.raises(ValueError):
            ring.write(b"\x00" * 10)  # wrong size for a 4x4x3 slot
    finally:
        ring.unlink()


def test_a_second_process_can_attach_and_read_a_written_frame() -> None:
    """Not just same-process round-trip — attach by name, the way the
    trust inspector (a different process) actually will."""
    writer = FrameRing(width=4, height=4, create=True)
    try:
        payload = bytes(range(4 * 4 * 3 % 256)) * 4
        payload = (payload * ((4 * 4 * 3 // len(payload)) + 1))[: 4 * 4 * 3]
        slot = writer.write(payload)

        reader = FrameRing(width=4, height=4, name=writer.name, create=False)
        try:
            assert reader.read(slot) == payload
        finally:
            reader.close()  # reader detaches, does NOT unlink
    finally:
        writer.unlink()
