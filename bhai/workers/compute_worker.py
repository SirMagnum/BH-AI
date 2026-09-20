"""
Compute worker — Phase 1 STUB, inert until Phase 3.

This is the process OCR, UIA/AX extraction, embeddings and local-LLM calls
will run in (§2.8) — anything holding the CPU for >50ms, never a thread in
the main Qt process. Unlike the capture worker, its lifetime does not
encode privacy state: it may be restarted freely, and its death degrades
features ("no OCR -> UIA-only mode") rather than pausing the session.

Not yet spawned by SessionManager — there is nothing for it to do until
Phase 3. Present now so the three-process topology in the architecture
doc is real from day one rather than retrofitted.
"""

from __future__ import annotations

from typing import Any


def run(stop_event: Any) -> None:
    while not stop_event.is_set():
        stop_event.wait(timeout=0.1)
