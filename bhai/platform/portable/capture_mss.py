"""
`mss`-backed `CaptureSource` — the portable fallback per roadmap §1, and
right now the ONLY backend, on both the graded platform and the dev one.

Not throwaway: this is permanent shipped code (the documented fallback
path), not a placeholder for `dxcam`. When the Windows backend lands, it
becomes a second implementation of the same interface, selected by
`bhai.platform.select`.
"""

from __future__ import annotations

import time

import mss

from bhai.platform.interfaces import CaptureSource, MonitorInfo, RawFrame


class MssCaptureSource(CaptureSource):
    def __init__(self) -> None:
        self._sct = mss.MSS()

    def list_monitors(self) -> list[MonitorInfo]:
        # mss.monitors[0] is the "all monitors combined" virtual bounding
        # box — skip it, we only want addressable individual monitors.
        infos = []
        for i, mon in enumerate(self._sct.monitors[1:], start=1):
            infos.append(
                MonitorInfo(
                    id=str(i),
                    left=mon["left"],
                    top=mon["top"],
                    width=mon["width"],
                    height=mon["height"],
                    # mss reports physical pixels, no scale-factor concept
                    # of its own. 1.0 is correct for it; real per-monitor
                    # DPI awareness is a `dxcam`/WGC-backend concern
                    # (roadmap Phase 2 "possible blockers": DPI maths).
                    scale_factor=1.0,
                )
            )
        return infos

    def grab(self, monitor_id: str) -> RawFrame:
        index = int(monitor_id)
        mon = self._sct.monitors[index]
        shot = self._sct.grab(mon)
        # mss gives BGRA; downstream (redaction, dHash) wants tightly
        # packed RGB — convert once here rather than making every
        # consumer know about mss's byte order.
        rgb = _bgra_to_rgb(shot.bgra, shot.width, shot.height)
        return RawFrame(
            rgb=rgb, width=shot.width, height=shot.height, monitor_id=monitor_id, ts=time.time()
        )

    def close(self) -> None:
        self._sct.close()


def get_monitor_signature(monitor_id: str) -> str:
    """Cheap lookup — enumerates monitors without grabbing a frame.

    Used by SessionManager to resolve which saved blocked-regions apply
    before spawning a capture worker, and by the worker itself to detect
    a resolution change mid-session (see workers/capture_worker.py).
    """
    source = MssCaptureSource()
    try:
        for info in source.list_monitors():
            if info.id == monitor_id:
                return f"{info.width}x{info.height}"
        raise ValueError(f"no monitor with id {monitor_id!r}")
    finally:
        source.close()


def _bgra_to_rgb(bgra: bytes, width: int, height: int) -> bytes:
    """Strip the alpha/padding byte and swap channel order. Pure-Python
    slicing rather than pulling in numpy just for this — profile later if
    it shows up as a bottleneck (Phase 2 DoD has a real latency budget)."""
    out = bytearray(width * height * 3)
    out[0::3] = bgra[2::4]  # R
    out[1::3] = bgra[1::4]  # G
    out[2::3] = bgra[0::4]  # B
    return bytes(out)
