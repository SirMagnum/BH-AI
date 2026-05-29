"""
BH-AI — Entry Point
Usage:
  python main.py           → Dev Mode (full debug dashboard)
  python main.py --user    → User Mode (compact floating pill HUD)
  python main.py --dev     → Dev Mode (explicit)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def main():
    mode = "dev"
    if "--user" in sys.argv:
        mode = "user"
    elif "--dev" in sys.argv:
        mode = "dev"

    if mode == "user":
        from src.ui_user import UserModeUI
        app = UserModeUI()
    else:
        from src.ui import AssistantUI
        app = AssistantUI()

    app.run()


if __name__ == "__main__":
    main()
