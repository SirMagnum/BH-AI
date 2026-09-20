# BH-AI — Contextual Desktop Companion

A privacy-first desktop assistant that watches your screen only while a
session is active, remembers the whole work session, and can point at
your screen to teach you. See `../PROJECT_CONTEXT.md` and
`../contextual-desktop-companion-roadmap.md` (v2.0) for the full plan —
this file covers only what's runnable today.

**Windows is the graded deliverable; macOS is a development target.**
See `PROJECT_CONTEXT.md §6a`. Everything below runs on both.

---

## Status

**Phase 1 done.** Session state machine, worker supervisor, event bus,
SQLite store, and a Qt shell (dashboard + pill HUD + tray).

**Phase 2 in progress.** Real capture is live: a `CaptureSource`
interface with an `mss` backend, an **allowlist** applied inside the
capture worker before anything else can see a frame — the AI sees
NOTHING by default, only the areas you've explicitly marked watchable —
dHash-based change scoring with adaptive backoff, a shared-memory ring
buffer, a **"See what the AI sees" trust inspector**, and a **watch-area
editor** — drag on a live preview to mark an area visible; it's saved
immediately and a real session actually applies it. Regions are also
fail-closed on resolution change: they're scoped to the exact monitor
size they were drawn for, and the capture worker stops itself (rather
than guessing)
if the screen's resolution changes mid-session. Not yet built: the
sensitive-window denylist and the `dxcam`/WGC Windows backend (needs the
Windows machine). No perception, memory, or LLM yet — Phases 3–5.

A `src/` prototype (tkinter, Windows-only) still exists for comparison —
see `docs/adr/0009-python-qt-stack.md` for why it was migrated off.

## Setup

```bash
cd BH-AI
python3 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Run

```bash
python main.py                     # the Phase 1+ app (PySide6)
python main.py --legacy            # the original tkinter prototype (Windows only)
python main.py --legacy --user     # legacy prototype's pill-HUD mode
```

The app opens a dev dashboard, a floating pill HUD, and a tray icon.
Start/Pause/Resume/End drive a real session state machine; the event log
panel shows every bus event live. There is no real screen capture yet —
the capture worker is a Phase 1 stub whose only job is to prove the
**process lifecycle** is correct (it exists exactly while the session is
`ACTIVE`, and Task Manager / Activity Monitor will show its PID appear
and disappear on Start/Pause).

## Test

```bash
pytest                             # 90 tests
ruff check bhai tests
```

Two tests to read first if you want to understand the privacy guarantee:
- `tests/test_supervisor_and_manager.py::test_pause_kills_the_capture_process_at_the_os_level`
  — starts a session, records the capture worker's real PID, calls
  `pause()`, and asserts via `psutil` that the OS agrees the process is
  dead. Not "we think it's paused" — the PID is gone.
- `tests/test_capture_integration.py::test_full_screen_blocked_region_makes_every_frame_all_black`
  — the adversarial redaction test, end to end: blocks the entire
  monitor, captures a **real** screenshot through the real IPC boundary,
  and asserts every byte that reaches the other side is black.

## Layout

```
bhai/
  session/      state machine (states.py), SessionManager, WorkerSupervisor
  workers/      capture_worker.py (real pipeline), compute_worker.py (inert until Phase 3)
  capture/      watch_regions.py (allowlist), change.py (dHash), trigger.py (adaptive backoff), ring.py (shared memory)
  bus/          typed events (Pydantic), asyncio pub/sub, the one Qt bridge
  db/           SQLite schema v1 + SessionStore (WAL, atomic session delete)
  platform/     interfaces.py (CaptureSource) + portable/capture_mss.py; windows/macos empty until dxcam/AX land
  ui/           dashboard, pill HUD, tray, trust inspector, shared theme
tests/          FSM properties, OS-level lifecycle, capture pipeline + integration, platform-isolation lint
spikes/         Phase 0 feasibility spikes with written verdicts
docs/adr/       Architecture Decision Records
src/            legacy tkinter prototype — reference only, not the trunk
```

## Privacy notes (current, honest state)

- No network calls anywhere in this codebase yet.
- Real screen capture is live via `mss`. What survives is an
  **allowlist, not a denylist**: the AI sees nothing at all unless a
  watch area has been explicitly drawn — with zero configuration, every
  frame comes back fully black. This is applied **inside the capture
  worker process**, before the frame is written to shared memory and
  before anything else — including the trust inspector — can see it.
  `apply_watch_regions()` (`bhai/capture/watch_regions.py`) is the one
  function in this codebase every teammate should be able to read end to
  end in one pass.
- Watch areas are drawn via the editor (tray → "What can the AI
  watch?…"), saved the moment you release the drag, and scoped to the
  exact monitor resolution they were drawn for — they never silently
  apply to a different resolution. If the screen's resolution changes
  mid-session, the capture worker stops itself (fail-closed) rather than
  keep capturing against a mismatched region set.
- Ending a session without saving deletes every row for that session in
  one transaction — verified by test, not asserted in a doc.
