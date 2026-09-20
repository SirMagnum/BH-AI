"""
BH-AI — Entry Point

Usage:
  python main.py             → the Phase 1+ app (PySide6, this is the trunk)
  python main.py --legacy    → the original tkinter prototype (src/), kept
                                for comparison only — see roadmap §1 for why
                                it was migrated off.

Everything runs inside `if __name__ == "__main__":`. This is not style —
it is required. On macOS/Windows, `multiprocessing`'s spawn start method
re-executes this entire file inside every worker child process (as
`__mp_main__`, to reconstruct the parent's module state). Without the
guard, every capture-worker spawn would recursively try to build a whole
second app inside the child, which is exactly the
"An attempt has been made to start a new process before the current
process has finished its bootstrapping phase" crash. See roadmap Phase 1
"possible blockers" — this is the same trap, just previously only fixed
in the throwaway smoke-test scripts and not here.
"""

import sys


def _run() -> None:
    if "--legacy" in sys.argv:
        sys.argv.remove("--legacy")
        mode = "user" if "--user" in sys.argv else "dev"
        if mode == "user":
            from src.ui_user import UserModeUI

            UserModeUI().run()
        else:
            from src.ui import AssistantUI

            AssistantUI().run()
    else:
        from bhai.ui.app import main

        sys.exit(main())


if __name__ == "__main__":
    _run()
