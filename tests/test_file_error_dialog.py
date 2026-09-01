"""
The blocking dialog shown when the data bundle fails validation.

Both buttons reach outside the process -- one opens a file browser, the other
quits the application -- so both are stubbed. Letting either run for real would
spray Finder windows across the machine or kill the test session.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from viewscope import config
from viewscope.dialogs import file_error_dialog as dialog_module
from viewscope.dialogs.file_error_dialog import FileErrorDialog

TITLE = "Validation Error: missing viewpoints"
MESSAGE = "Error: plan.json was expecting 185 viewpoints but received 10 viewpoints."
ACTION = "Tip: Open the Data folder and replace your files."


@pytest.fixture
def dialog(qapp):
    return FileErrorDialog(TITLE, MESSAGE, ACTION)


@pytest.fixture
def opened_folders(monkeypatch):
    """Record what would have been opened, without opening anything."""
    calls = []
    monkeypatch.setattr(dialog_module.subprocess, "run", lambda args: calls.append(args))
    monkeypatch.setattr(
        dialog_module.os, "startfile", lambda path: calls.append(path), raising=False
    )
    return calls


# -- What it says ------------------------------------------------------


def test_the_dialog_shows_the_error(dialog):
    assert dialog.windowTitle() == TITLE
    assert dialog.message.text() == MESSAGE
    assert dialog.action.text() == ACTION


def test_a_multiline_message_survives(qapp):
    """Regression: the action tip is a triple-quoted block with newlines."""
    action = "line one\nline two\nline three"

    dialog = FileErrorDialog(TITLE, MESSAGE, action)

    assert dialog.action.text() == action


# -- How it behaves ----------------------------------------------------


def test_the_dialog_blocks_the_application(dialog):
    """Carrying on behind a bad bundle would render an empty scene."""
    assert dialog.windowModality() == Qt.WindowModality.ApplicationModal


def test_the_dialog_cannot_be_dismissed_by_the_close_button(dialog):
    """The user has to choose one of the two offered actions."""
    assert not (dialog.windowFlags() & Qt.WindowType.WindowCloseButtonHint)


def test_the_dialog_is_wide_enough_for_a_file_list(dialog):
    assert dialog.minimumWidth() >= 500


# -- The buttons -------------------------------------------------------


def test_opening_the_folder_points_at_the_data_directory(dialog, opened_folders, monkeypatch):
    monkeypatch.setattr(dialog_module.sys, "platform", "darwin")

    dialog.open_folder_button.click()

    assert opened_folders == [["open", config.DATA_DIR]]


def test_opening_the_folder_uses_the_linux_helper(dialog, opened_folders, monkeypatch):
    monkeypatch.setattr(dialog_module.sys, "platform", "linux")

    dialog.open_folder_button.click()

    assert opened_folders == [["xdg-open", config.DATA_DIR]]


def test_opening_the_folder_uses_the_windows_helper(dialog, opened_folders, monkeypatch):
    monkeypatch.setattr(dialog_module.sys, "platform", "win32")

    dialog.open_folder_button.click()

    assert opened_folders == [config.DATA_DIR]


def test_exiting_closes_the_dialog_first(dialog, monkeypatch):
    """
    The quit is deferred through a timer on purpose: tearing down the VTK
    renderer while the dialog is still up crashes. Stub the timer so the test
    session survives, and check the dialog rejected.
    """
    scheduled = []
    monkeypatch.setattr(
        dialog_module.QTimer,
        "singleShot",
        staticmethod(lambda ms, fn: scheduled.append(ms)),
    )

    dialog.exit_button.click()

    assert dialog.result() == FileErrorDialog.DialogCode.Rejected
    assert scheduled == [50]
