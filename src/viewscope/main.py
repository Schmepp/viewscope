"""ViewScope desktop viewer: entry point.

uv run viewscope
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import config

# from .window import MainWindow
from . import window as wd


def main() -> int:
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
