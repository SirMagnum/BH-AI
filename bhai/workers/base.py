"""
Generic worker-process handle: spawn, and terminate with escalation.

Termination escalates: ask nicely (stop_event) -> SIGTERM -> SIGKILL. A
worker that ignores its stop_event for more than `timeout` seconds gets
killed outright — a privacy-critical process must never be able to
refuse to die, because "refuse to die" and "keep capturing" look
identical from the user's side.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerHandle:
    process: multiprocessing.Process
    stop_event: Any  # multiprocessing.synchronize.Event — untyped, no public stub
    started_at: float

    @property
    def pid(self) -> int | None:
        return self.process.pid

    @property
    def is_alive(self) -> bool:
        return self.process.is_alive()

    def terminate(self, timeout: float = 2.0) -> None:
        if not self.process.is_alive():
            return
        self.stop_event.set()
        self.process.join(timeout)
        if self.process.is_alive():
            self.process.terminate()  # SIGTERM
            self.process.join(timeout)
        if self.process.is_alive():
            self.process.kill()  # SIGKILL
            self.process.join()


def spawn(target: Callable[..., None], args: tuple = ()) -> WorkerHandle:
    """Spawn a daemon process running `target(stop_event, *args)`.

    `daemon=True` gives us best-effort cleanup if the parent exits normally
    (Python's multiprocessing._exit_function joins daemonic children). It
    is NOT a substitute for the explicit terminate() calls the session
    manager makes on every state transition — daemon status is a safety
    net, not the mechanism. A hard parent-death watchdog (Job Object on
    Windows, a POSIX equivalent on macOS/Linux) is real work, tracked as
    a Phase 1/2 follow-up rather than built here.
    """
    stop_event = multiprocessing.Event()
    process = multiprocessing.Process(target=target, args=(stop_event, *args), daemon=True)
    process.start()
    return WorkerHandle(process=process, stop_event=stop_event, started_at=time.time())
