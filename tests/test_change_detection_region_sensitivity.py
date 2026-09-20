"""
Regression test for a real bug reported in manual testing: "if I change
screens or get another app in [the watch] area, I can't see the new
captures." The cause was `dhash()` running on the whole (mostly
guaranteed-black) redacted frame — a small watch region's real content
change got diluted away by the coarse full-frame downsample, so the
trigger policy wrongly concluded the screen was static and backed off
toward its slowest interval.

`dhash_region()` fixes this by hashing only the watched area's bounding
box. These tests prove the specific failure mode directly: a change
happening entirely inside a small watch region must be detected, even
though hashing the whole frame would miss it.
"""

from __future__ import annotations

import numpy as np

from bhai.capture.change import change_score, dhash, dhash_region, watch_regions_bounding_box
from bhai.capture.trigger import _CHANGE_THRESHOLD, TriggerPolicy
from bhai.capture.watch_regions import WatchRegion
from bhai.platform.interfaces import RawFrame


def _frame_with_marker(width: int, height: int, box: tuple[int, int, int, int]) -> RawFrame:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = box
    arr[y1:y2, x1:x2, :] = 255
    return RawFrame(rgb=arr.tobytes(), width=width, height=height, monitor_id="1", ts=0.0)


def _frame_with_stripes(width: int, height: int, box: tuple[int, int, int, int]) -> RawFrame:
    """A flat colour fill has zero internal gradient, so dHash — which
    only encodes "is this pixel brighter than its right neighbour" —
    cannot distinguish uniform black from uniform white at all,
    regardless of cropping. Real UI content (text, icons, window
    chrome) is full of edges, unlike a flat fill, so alternating
    columns inside the box is the more honest stand-in for "something
    actually appeared here"."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = box
    for col in range(x1, x2, 2):
        arr[y1:y2, col, :] = 255
    return RawFrame(rgb=arr.tobytes(), width=width, height=height, monitor_id="1", ts=0.0)


def _solid_frame(width: int, height: int, value: int = 0) -> RawFrame:
    arr = np.full((height, width, 3), value, dtype=np.uint8)
    return RawFrame(rgb=arr.tobytes(), width=width, height=height, monitor_id="1", ts=0.0)


def test_bounding_box_of_no_regions_is_none() -> None:
    assert watch_regions_bounding_box([], 800, 600) is None


def test_bounding_box_covers_the_union_of_multiple_regions() -> None:
    regions = [WatchRegion(x=0.1, y=0.1, w=0.1, h=0.1), WatchRegion(x=0.5, y=0.5, w=0.2, h=0.2)]
    box = watch_regions_bounding_box(regions, 1000, 1000)
    assert box == (100, 100, 700, 700)


def test_a_change_diluted_away_by_whole_frame_hashing_is_caught_by_region_hashing() -> None:
    """The exact bug: a small watch region (10% of the frame) changes
    entirely from black to white INSIDE itself. What matters isn't
    whether whole-frame dHash registers literally zero difference — it's
    whether the score crosses TriggerPolicy's actual threshold for
    "something changed, go fast again". Diluted by the whole frame, it
    must NOT cross that threshold (that's the bug, reproduced against
    the real trigger logic); scoped to the region, it must (the fix)."""
    width, height = 800, 600
    small_region = WatchRegion(x=0.85, y=0.85, w=0.1, h=0.1)  # small corner, like a real selection
    box = watch_regions_bounding_box([small_region], width, height)
    x1, y1, x2, y2 = box

    before = _solid_frame(width, height, value=0)  # watched area starts black
    after = _frame_with_stripes(width, height, (x1, y1, x2, y2))  # watched area gets real content

    whole_frame_score = change_score(dhash(before), dhash(after))
    region_score = change_score(
        dhash_region(before, [small_region]), dhash_region(after, [small_region])
    )

    assert whole_frame_score < _CHANGE_THRESHOLD, (
        "expected whole-frame hashing to stay BELOW the real trigger threshold for this "
        "change (that's the bug) — if this fails, the bug may already be gone and this "
        "test's premise is stale"
    )
    assert region_score >= _CHANGE_THRESHOLD, (
        "region-scoped hashing must cross the real trigger threshold for a change "
        "entirely inside the watch area"
    )

    # And the practical consequence, against the real TriggerPolicy: after
    # several quiet ticks have backed it off, a whole-frame score leaves
    # it backed off (or backs it off further); a region score resets it
    # to the fastest level.
    whole_frame_trigger = TriggerPolicy()
    for _ in range(3):
        whole_frame_trigger.on_change_score(0.0)
    assert whole_frame_trigger.level > 0  # confirm it's actually backed off before the real check
    whole_frame_trigger.on_change_score(whole_frame_score)
    assert whole_frame_trigger.level > 0, "a diluted whole-frame score should not reset the trigger"

    region_trigger = TriggerPolicy()
    for _ in range(3):
        region_trigger.on_change_score(0.0)
    region_trigger.on_change_score(region_score)
    assert region_trigger.level == 0, "region score should reset the trigger to its fastest level"


def test_dhash_region_falls_back_to_whole_frame_with_no_regions() -> None:
    frame = _solid_frame(64, 64, value=50)
    assert dhash_region(frame, []) == dhash(frame)


def test_dhash_region_ignores_changes_entirely_outside_the_watch_region() -> None:
    """The complementary property: a change OUTSIDE the watched area
    must not affect the region-scoped hash at all — consistent with that
    area being redacted to black and irrelevant regardless."""
    width, height = 800, 600
    region = WatchRegion(x=0.0, y=0.0, w=0.2, h=0.2)  # top-left only

    before = _solid_frame(width, height, value=0)
    # A big change far outside the watch region (bottom-right quadrant).
    after = _frame_with_marker(width, height, (600, 450, 800, 600))

    assert dhash_region(before, [region]) == dhash_region(after, [region])
