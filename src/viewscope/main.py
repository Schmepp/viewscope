"""
ViewScope desktop viewer: entry point.

uv run viewscope
"""

from __future__ import annotations

import os
import platform
import sys

from PySide6.QtWidgets import QApplication

from viewscope import config
from viewscope.startup import StartupWindow


def main() -> int:
    # Required for running headless on Linux
    if platform.system() == "Linux":
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

    app = QApplication(sys.argv)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationName(config.APP_NAME)

    # The startup screen opens the viewer itself, once a project is loaded.
    startup = StartupWindow()
    startup.show()
    startup.raise_()
    startup.activateWindow()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
