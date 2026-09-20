"""
Change detection — dHash + Hamming distance (roadmap §2.2 Tier 1/2).

Runs on the REDACTED frame, never the raw one — it is downstream of
`apply_watch_regions()` in the capture worker's pipeline, same as
everything else. This is what lets the trigger policy back off to
10s/30s/60s heartbeats when the screen is static, which is most of a
real work session (reading, thinking, a video playing in a paused
state) and is exactly the cost the tiered cascade in §2.2 exists to
avoid paying at full rate.

`dhash_region()` exists because of a real bug hit in manual testing:
hashing the WHOLE frame after the allowlist model landed meant hashing
mostly guaranteed-black padding. dHash's coarse 8x8 downsample samples
uniformly across the full frame, so a small watch region contributed
almost nothing to the hash — real changes inside it got diluted away,
the trigger concluded "nothing's changing," and backed off to a 60s
interval while the user was actively looking at something that WAS
changing. Hashing just the watched area's bounding box keeps
sensitivity proportional to what's actually visible, not to how much of
the screen is (correctly, deliberately) black.
"""

from __future__ import annotations

import numpy as np

from bhai.capture.watch_regions import WatchRegion
from bhai.platform.interfaces import RawFrame

_HASH_SIZE = 8  # 8x8 → 64-bit hash, the standard dHash size


def _dhash_array(arr: np.ndarray, hash_size: int = _HASH_SIZE) -> int:
    """Difference hash over an (h, w, 3) uint8 array directly — shared by
    `dhash()` and `dhash_region()` so cropping is just a slice, not a
    second implementation."""
    h, w = arr.shape[0], arr.shape[1]
    if h < 2 or w < 2:
        return 0  # degenerate crop (e.g. a zero-height region) — nothing to hash

    # Greyscale via the standard luma weights, then a crude but fast
    # nearest-neighbour downscale — this runs on every trigger, so it
    # stays index-based rather than pulling in a resampling filter.
    grey = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.float32)
    row_idx = np.linspace(0, h - 1, hash_size).astype(int)
    col_idx = np.linspace(0, w - 1, hash_size + 1).astype(int)
    small = grey[np.ix_(row_idx, col_idx)]

    diff = small[:, :-1] > small[:, 1:]
    bits = diff.flatten()

    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def dhash(frame: RawFrame, hash_size: int = _HASH_SIZE) -> int:
    """Difference hash over the whole frame. Two frames with a similar
    hash look similar; a single Hamming-distance number then stands in
    for "how much did the screen change". Prefer `dhash_region()` when
    you have watch regions — see module docstring for why."""
    arr = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(frame.height, frame.width, 3)
    return _dhash_array(arr, hash_size)


def watch_regions_bounding_box(
    regions: list[WatchRegion], width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Union bounding box of every watch region, in pixel coordinates.
    None if there are no regions at all."""
    if not regions:
        return None
    x1 = min(r.x for r in regions)
    y1 = min(r.y for r in regions)
    x2 = max(r.x + r.w for r in regions)
    y2 = max(r.y + r.h for r in regions)
    px1, py1 = max(0, int(x1 * width)), max(0, int(y1 * height))
    px2 = min(width, int(round(x2 * width)))
    py2 = min(height, int(round(y2 * height)))
    return px1, py1, px2, py2


def dhash_region(frame: RawFrame, regions: list[WatchRegion], hash_size: int = _HASH_SIZE) -> int:
    """Same as `dhash()`, but computed only over the union bounding box
    of the given watch regions. Falls back to hashing the whole frame
    when there are none — in that case the frame is already all black
    (roadmap §2.4's safe default) and the fallback is harmless, since
    there's nothing to be sensitive to either way."""
    box = watch_regions_bounding_box(regions, frame.width, frame.height)
    if box is None:
        return dhash(frame, hash_size)
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return dhash(frame, hash_size)
    arr = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(frame.height, frame.width, 3)
    return _dhash_array(arr[y1:y2, x1:x2, :], hash_size)


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def change_score(hash_a: int, hash_b: int, hash_size: int = _HASH_SIZE) -> float:
    """Normalized to [0, 1]: 0 = identical, 1 = maximally different."""
    total_bits = hash_size * hash_size
    return hamming_distance(hash_a, hash_b) / total_bits
