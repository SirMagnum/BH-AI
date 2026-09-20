"""
Shared-memory ring buffer (roadmap §2.2 "Frame representation").

Frames cross the capture-worker → main-process boundary via a fixed-size
shared-memory ring, never by pickling image bytes on a queue — a 4K
frame is ~24MB; queueing that at even 2 FPS would destroy the app. Only
a `FrameDescriptor` — the ring's name, slot index, and metadata — crosses
process boundaries, and it is small enough to go on an ordinary
`multiprocessing.Queue` or the event bus.

One ring per (width, height) for the life of a session. A monitor or
resolution change is a fail-closed pause + re-confirm per roadmap §2.4,
never a resize of an existing ring — so a ring's slot size is fixed for
its entire lifetime and this class does not support resizing.
"""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import shared_memory

# roadmap §2.2: "a fixed-size ring buffer of the last ~20 ... frames"
RING_SIZE = 20


@dataclass(frozen=True)
class FrameDescriptor:
    """The ONLY thing that crosses a process boundary for a captured
    frame — never the pixels themselves."""

    shm_name: str
    slot: int
    width: int
    height: int
    monitor_id: str
    frame_ts: float
    change_score: float


class FrameRing:
    """Owns one shared-memory block sized for RING_SIZE frames of a fixed
    width/height.

    The capture worker is always the creator (`create=True`) and the only
    writer. Read-only consumers (the trust inspector, later perception)
    attach via `create=False` with the same `name`.
    """

    def __init__(
        self, width: int, height: int, name: str | None = None, create: bool = True
    ) -> None:
        self.width = width
        self.height = height
        self._slot_bytes = width * height * 3
        total_bytes = self._slot_bytes * RING_SIZE
        if create:
            self._shm = shared_memory.SharedMemory(create=True, size=total_bytes, name=name)
        else:
            if name is None:
                raise ValueError("attaching to an existing ring requires its shm `name`")
            self._shm = shared_memory.SharedMemory(name=name)
        self._next_slot = 0

    @property
    def name(self) -> str:
        return self._shm.name

    def write(self, rgb: bytes) -> int:
        """Write into the next slot (wrapping), return the slot index used."""
        if len(rgb) != self._slot_bytes:
            raise ValueError(
                f"frame size {len(rgb)} does not match ring slot size {self._slot_bytes} "
                f"({self.width}x{self.height}x3) — a resolution change must pause the "
                f"session and open a new ring, never write into this one"
            )
        slot = self._next_slot
        offset = slot * self._slot_bytes
        self._shm.buf[offset : offset + self._slot_bytes] = rgb
        self._next_slot = (slot + 1) % RING_SIZE
        return slot

    def read(self, slot: int) -> bytes:
        offset = slot * self._slot_bytes
        return bytes(self._shm.buf[offset : offset + self._slot_bytes])

    def close(self) -> None:
        """Detach from the shared memory. Safe for both writer and readers."""
        self._shm.close()

    def unlink(self) -> None:
        """Release the OS-level shared memory segment entirely. Only the
        creator (capture worker) calls this, on shutdown — calling it
        from a reader would pull the rug out from under everyone else
        still attached."""
        self._shm.close()
        self._shm.unlink()
