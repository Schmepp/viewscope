"""
Unit tests for src/viewscope/main.py.

main() opens a window and blocks in the Qt event loop, so the loop and the
window are both stubbed out. What is left worth checking is the wiring:
the app is named, the window is shown, and the exit code is passed back.
"""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

from viewscope import config
from viewscope import main as main_module


@pytest.fixture
def stub_app(qapp, monkeypatch):
    """
    Reuse the session QApplication and never enter its event loop.

    Qt allows only one QApplication per process, so main()'s constructor is
    redirected at the existing instance.
    """
    monkeypatch.setattr(main_module, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    return qapp


@pytest.fixture
def stub_window(monkeypatch):
    """Record what main() does to the window, without building a real one."""

    class StubWindow:
        instances = []

        def __init__(self, data_dir):
            self.data_dir = data_dir
            self.calls = []
            StubWindow.instances.append(self)

        def __getattr__(self, name):
            return lambda *args: self.calls.append(name)

    StubWindow.instances = []
    monkeypatch.setattr(main_module.wd, "MainWindow", StubWindow)
    return StubWindow


def test_main_returns_the_event_loop_exit_code(stub_app, stub_window, monkeypatch):
    monkeypatch.setattr(QApplication, "exec", lambda self: 3)
    assert main_module.main() == 3


def test_main_names_the_application(stub_app, stub_window):
    """QSettings keys off these, so the saved layout depends on them."""
    main_module.main()

    assert stub_app.organizationName() == config.ORG_NAME
    assert stub_app.applicationName() == config.APP_NAME


def test_main_opens_the_window_on_the_default_bundle(stub_app, stub_window):
    main_module.main()

    window = stub_window.instances[-1]
    assert window.data_dir == config.DATA_DIR
    assert window.calls == ["show", "raise_", "activateWindow", "start"]


@pytest.mark.skipif(sys.platform != "linux", reason="the EGL fallback is Linux only")
def test_main_selects_egl_on_linux(stub_app, stub_window, monkeypatch):
    """Headless Linux has no GLX, so pyrender is pointed at EGL."""
    monkeypatch.delenv("PYOPENGL_PLATFORM", raising=False)

    main_module.main()

    assert main_module.os.environ["PYOPENGL_PLATFORM"] == "egl"
