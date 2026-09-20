"""
Regression test for a real bug hit in manual testing: `main.py` had no
`if __name__ == "__main__":` guard around its dispatch logic. On macOS
(and Windows), multiprocessing's spawn start method re-executes the
ENTIRE entry-point file inside every worker child process, to reconstruct
the parent's `__main__` module state. Without the guard, that
re-execution rebuilt a whole second QApplication/SessionManager inside
the capture worker — harmless-looking on the first session, but the
second `start()` (a fresh spawn) crashed with:

    RuntimeError: An attempt has been made to start a new process before
    the current process has finished its bootstrapping phase...

Two checks:
  1. Static — main.py's dispatch logic must live inside the guard. Cheap,
     and catches the exact regression that happened.
  2. Dynamic — two full session start/end cycles must survive in a REAL
     subprocess (not an import: the bug is about __main__ identity,
     which importing this test module does not reproduce).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_main_py_guards_its_dispatch_logic() -> None:
    text = (REPO_ROOT / "main.py").read_text()
    guard_lines = [
        i for i, line in enumerate(text.splitlines()) if "__name__" in line and "__main__" in line
    ]
    assert guard_lines, (
        'main.py must guard its dispatch logic with `if __name__ == "__main__":` — '
        "without it, multiprocessing's spawn start method re-executes the whole file "
        "inside every worker child process (see bhai/workers/base.py's spawn() docstring)."
    )
    after_guard = "\n".join(text.splitlines()[guard_lines[0] :])
    assert "_run()" in after_guard or "main()" in after_guard, (
        "found an `if __name__ == '__main__':` line, but nothing inside it actually "
        "calls the dispatcher — the guard must wrap the real entry point, not sit unused"
    )


def test_two_sequential_sessions_do_not_trigger_recursive_spawn(tmp_path) -> None:
    """Drives SessionManager through two full start/end cycles inside a
    REAL subprocess (`python <file>.py`), the only way to faithfully
    reproduce spawn's __main__ re-execution behaviour."""
    db_path = tmp_path / "regress.db"
    script = textwrap.dedent(f"""
        import asyncio, sys
        sys.path.insert(0, {str(REPO_ROOT)!r})

        def _run():
            import qasync
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from bhai.bus.bus import EventBus
            from bhai.db.store import SessionStore
            from bhai.session.manager import SessionManager

            app = QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            loop = qasync.QEventLoop(app)
            asyncio.set_event_loop(loop)

            store = SessionStore({str(db_path)!r})
            bus = EventBus()
            manager = SessionManager(bus, store)

            def cycle_one():
                manager.start()
                QTimer.singleShot(300, end_one)

            def end_one():
                manager.pause(); manager.end(); manager.finish(save=False)
                QTimer.singleShot(150, cycle_two)

            def cycle_two():
                manager.start()  # the spawn that crashed before the __main__ guard fix
                QTimer.singleShot(300, finish)

            def finish():
                manager.pause(); manager.end(); manager.finish(save=False)
                print("OK")
                manager.shutdown(); store.close(); app.quit()

            QTimer.singleShot(150, cycle_one)
            with loop:
                loop.run_forever()

        if __name__ == "__main__":
            _run()
    """)
    script_path = tmp_path / "driver.py"
    script_path.write_text(script)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert "OK" in result.stdout, (
        f"two sequential session starts crashed in a real subprocess.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "RuntimeError" not in result.stderr
