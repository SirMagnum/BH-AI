# ADR-0009: Replace Tauri + Rust + React with pure Python + PySide6

**Status:** Accepted
**Date:** 2026-09-20
**Supersedes:** the stack described in roadmap v1.0 §1–§2.8

## Context

Roadmap v1.0 specified Tauri 2 (Rust) + React + TypeScript for the shell,
overlay, and session state machine, with a Python/FastAPI sidecar for
orchestration. Reviewing that plan against the team's actual working
prototype (`src/`, tkinter) and hardware surfaced two problems:

1. The prototype and the plan share no code and no stack. Nobody on the
   team had `cargo` installed.
2. The team's primary development machine is a Mac; the graded
   deliverable is Windows. Tauri's overlay primitives are cross-platform
   in principle, but the team had validated none of it.

## Decision

Drop Tauri, Rust, React, TypeScript, and the FastAPI sidecar. Build a
single Python application using PySide6 (Qt 6). Session state machine,
event bus, memory, and LLM routing all live in one process; capture and
compute work happens in separate OS processes for the reasons in
PROJECT_CONTEXT §8 invariant 1 and roadmap §2.8, not for a language
boundary.

## Evidence

`spikes/01-overlay/overlay_probe_qt.py`, run on the team's macOS machine:

| Property | tkinter (prototype) | PySide6 |
|---|---|---|
| Transparent overlay | `TclError: bad attribute "-transparentcolor"` | ✅ |
| Click-through | requires `ctypes.windll` (Windows-only) | ✅ `WindowTransparentForInput` |
| Always-on-top | ✅ | ✅ |
| `devicePixelRatio` (Retina/DPI) | — | ✅ reports `2.0` correctly |
| Annotation primitives (circle/arrow/box/label) | — | ✅ all render via `QPainter` |

Phase 1 build (`bhai/`) then verified the harder claim — that dropping
the Rust-owned capture handle does not weaken invariant 1 — with an
OS-level test (`tests/test_supervisor_and_manager.py`):
`test_pause_kills_the_capture_process_at_the_os_level` starts a session,
records the capture worker's PID, calls `pause()`, and asserts via
`psutil` (not our own bookkeeping) that the PID is dead. A second test
kills the capture process out-of-band (`os.kill(pid, 9)`) and asserts the
session degrades to `PAUSED` rather than silently respawning capture.

## Consequences

**Deleted, per roadmap §1's "why the Tauri + Rust stack was dropped":**
the WebSocket protocol, localhost bearer-token auth, PyInstaller sidecar
lifecycle / Job Objects, JSON-Schema-to-TypeScript codegen, and the
Rust↔Python frame-marshalling boundary. None of this was product value;
all of it was schedule risk for a part-time team.

**Changed:** invariant 1 (PROJECT_CONTEXT §8) is now enforced by an OS
process boundary (capture worker lifetime = session state) instead of a
language boundary. Argued to be *stronger* for an evaluator, since it is
independently checkable in Activity Monitor / Task Manager without
trusting anything the team wrote about Rust's ownership semantics.

**Lost:** raw capture throughput headroom (irrelevant — §2.2's
event-driven cascade means we were never throughput-bound); installer
size (irrelevant to the grade); a language-boundary privacy argument
(replaced, not removed).

**New CI gate:** `tests/test_platform_isolation.py` greps `bhai/` for
Windows- or macOS-specific markers outside `bhai/platform/{windows,macos}/`,
and asserts `WorkerSupervisor.spawn_capture`/`kill_capture` have exactly
one caller (`SessionManager`). This makes §6a and invariant 1 mechanically
enforced rather than a convention teammates might drift from under
deadline pressure.

## Alternatives considered

See roadmap §1 "Why the Tauri + Rust stack was dropped" for the full
comparison (Tauri shell + Python capture, Electron, keeping tkinter).
