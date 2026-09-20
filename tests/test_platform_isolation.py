"""
Enforces PROJECT_CONTEXT §6a / invariant 8: only `bhai/platform/*` may know
what OS it's running on. This is a CI gate, not a style guideline — a
teammate coupling the memory layer to a Win32 call should fail here, on
whatever machine runs it, rather than being discovered when someone else's
build breaks.

Scoped to `bhai/` only. The legacy prototype in `src/` is explicitly
Windows-only and excluded — it's kept for comparison (roadmap §12), not
part of the graded build this rule protects.
"""

from __future__ import annotations

import re
from pathlib import Path

BHAI_ROOT = Path(__file__).resolve().parent.parent / "bhai"

_WINDOWS_MARKERS = re.compile(r"\b(ctypes\.windll|win32\w*|pywin32|uiautomation)\b")
_MACOS_MARKERS = re.compile(r"\b(pyobjc|AppKit|Quartz|CoreGraphics|AXUIElement)\b")

_ALLOWED_WINDOWS_DIR = BHAI_ROOT / "platform" / "windows"
_ALLOWED_MACOS_DIR = BHAI_ROOT / "platform" / "macos"


def _all_py_files() -> list[Path]:
    return [p for p in BHAI_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_windows_specific_imports_outside_platform_windows() -> None:
    offenders = []
    for path in _all_py_files():
        if _ALLOWED_WINDOWS_DIR in path.parents:
            continue
        text = path.read_text()
        if _WINDOWS_MARKERS.search(text):
            offenders.append(str(path.relative_to(BHAI_ROOT.parent)))
    assert not offenders, (
        "Windows-specific code found outside bhai/platform/windows/: "
        f"{offenders}. Move it behind the platform interface (§6a)."
    )


def test_no_macos_specific_imports_outside_platform_macos() -> None:
    offenders = []
    for path in _all_py_files():
        if _ALLOWED_MACOS_DIR in path.parents:
            continue
        text = path.read_text()
        if _MACOS_MARKERS.search(text):
            offenders.append(str(path.relative_to(BHAI_ROOT.parent)))
    assert not offenders, (
        "macOS-specific code found outside bhai/platform/macos/: "
        f"{offenders}. Move it behind the platform interface (§6a)."
    )


def test_capture_worker_spawn_kill_has_exactly_one_caller() -> None:
    """Invariant 1: nothing but SessionManager (via WorkerSupervisor) may
    start or stop the capture worker. A second caller is exactly the kind
    of bypass this invariant exists to forbid."""
    callers = []
    for path in _all_py_files():
        if path.name in ("supervisor.py",):
            continue  # the implementation itself, not a caller
        text = path.read_text()
        if "spawn_capture(" in text or "kill_capture(" in text:
            callers.append(str(path.relative_to(BHAI_ROOT.parent)))
    assert callers == ["bhai/session/manager.py"], (
        f"Expected only SessionManager to call spawn_capture/kill_capture, found: {callers}"
    )
