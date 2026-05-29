"""
BH-AI — User Mode Entry Point
Compact floating pill HUD — pick a window, click Start.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.ui_user import UserModeUI


def main():
    app = UserModeUI()
    app.run()


if __name__ == "__main__":
    main()
