"""
BH-AI — Dev Mode Entry Point
Full debug dashboard with log console, FPS meter, OCR output, and insights panel.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.ui import AssistantUI


def main():
    app = AssistantUI()
    app.run()


if __name__ == "__main__":
    main()
