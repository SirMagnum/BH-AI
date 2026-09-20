"""
The fail-closed resolution check (roadmap §2.4): if a monitor changes
size or disappears mid-session, the capture worker must stop rather than
keep writing frames into a ring sized for the old resolution, or redact
regions drawn for a shape the screen no longer has.

Tested against a fake CaptureSource — no real display or resolution
change needed, and no dependence on this machine's actual monitor.
"""

from __future__ import annotations

from bhai.platform.interfaces import MonitorInfo
from bhai.workers.capture_worker import _monitor_still_matches


class _FakeSource:
    def __init__(self, monitors: list[MonitorInfo]) -> None:
        self._monitors = monitors

    def list_monitors(self) -> list[MonitorInfo]:
        return self._monitors

    def grab(self, monitor_id: str):  # pragma: no cover — unused by this check
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass


def _monitor(monitor_id: str, width: int, height: int) -> MonitorInfo:
    return MonitorInfo(id=monitor_id, left=0, top=0, width=width, height=height, scale_factor=1.0)


def test_matches_when_resolution_is_unchanged() -> None:
    source = _FakeSource([_monitor("1", 1920, 1080)])
    assert _monitor_still_matches(source, "1", 1920, 1080) is True


def test_fails_closed_when_resolution_changed() -> None:
    source = _FakeSource([_monitor("1", 1280, 720)])
    assert _monitor_still_matches(source, "1", 1920, 1080) is False


def test_fails_closed_when_monitor_disappears_entirely() -> None:
    source = _FakeSource([_monitor("2", 1920, 1080)])
    assert _monitor_still_matches(source, "1", 1920, 1080) is False


def test_matches_the_right_monitor_among_several() -> None:
    source = _FakeSource([_monitor("1", 1920, 1080), _monitor("2", 1280, 720)])
    assert _monitor_still_matches(source, "2", 1280, 720) is True
    assert _monitor_still_matches(source, "2", 1920, 1080) is False
