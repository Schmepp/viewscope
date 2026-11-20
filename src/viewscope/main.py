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
    
    # Configure Linux graphics and Qt platform settings before
    # QApplication initialization, since Qt selects its platform
    # plugin when the application instance is created.
    if platform.system() == "Linux":
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

        # Wayland restricts global cursor positioning, which is required by
        # ViewScope's viewport interaction. Use XCB through XWayland to preserve
        # this funtionality.
        if os.environ.get("WAYLAND_DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
            print("[Warning]: Wayland detected, using X11 compatibility mode...")

    app = QApplication(sys.argv)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationName(config.APP_NAME)

    # Set on the application rather than on a window: a tooltip is a top-level
    # window of its own and never inherits the stylesheet of whatever it is
    # describing.
    app.setStyleSheet(config.TOOLTIP_STYLE)

    # Display which platform is being selected during QApplication initialization
    if app.platformName() == "xcb":
        print("[Info]: Running with XCB compatibility.")

    elif app.platformName() == "wayland":
        print("[Info]: Running with native Wayland.")

    # The startup screen opens the viewer itself, once a project is loaded.
    startup = StartupWindow()
    startup.show()
    startup.raise_()
    startup.activateWindow()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
