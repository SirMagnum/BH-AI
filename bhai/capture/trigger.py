"""
Adaptive trigger policy (roadmap §2.2 Tier 1/2).

Not a fixed-FPS loop. The interval backs off the longer the screen stays
static and resets to the fast interval the moment real change appears —
this is most of what keeps idle CPU under the PROJECT_CONTEXT §6 budget
(<3% idle) without needing OS focus-change hooks yet (§2.2 Tier 0, not
built in Phase 2 — this policy is the fallback that works even without
them, and stays useful alongside them once they exist).
"""

from __future__ import annotations

_BACKOFF_STEPS_S = [0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
_CHANGE_THRESHOLD = 0.05  # fraction of dHash bits differing to count as "changed"


class TriggerPolicy:
    def __init__(self) -> None:
        self._level = 0

    @property
    def interval(self) -> float:
        return _BACKOFF_STEPS_S[self._level]

    @property
    def level(self) -> int:
        return self._level

    def on_change_score(self, score: float) -> None:
        """Call after every capture with its change_score (0..1)."""
        if score >= _CHANGE_THRESHOLD:
            self._level = 0
        else:
            self._level = min(self._level + 1, len(_BACKOFF_STEPS_S) - 1)

    def reset(self) -> None:
        self._level = 0
