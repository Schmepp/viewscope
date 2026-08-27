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
from viewscope import window as wd


def main() -> int:
    # Required for running headless on Linux
    if platform.system() == "Linux":
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

    app = QApplication(sys.argv)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationName(config.APP_NAME)

    window = wd.MainWindow(config.DATA_DIR)
    window.show()
    window.raise_()
    window.activateWindow()
    window.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
