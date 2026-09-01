"""
Spawning a camera from the Viewpoints panel's "Add Camera" button.

The click path is: button -> AddCameraDialog -> SCENE_STORE.add_camera ->
plan_changed -> the table refreshes and the viewport rebuilds its glyphs.
The dialog is modal, so it is replaced with a stub that answers immediately;
a real exec() would block the test run forever.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QDialog

from viewscope.camera.structs import CameraInfo
from viewscope.data.store import SCENE_STORE
from viewscope.dialogs.addcamera_dialog import AddCameraDialog
from viewscope.panels import viewpoints_panel as viewpoints_module
from viewscope.panels.viewpoints_panel import ViewpointsPanel


@pytest.fixture
def accepting_dialog(monkeypatch):
    """
    Replace AddCameraDialog with a stub the caller can program.

    Returns a setter: call it with the values the user "typed" and whether
    they pressed OK.
    """

    def install(values=(1.0, 2.0, 3.0, 45.0, -10.0), accepted=True):
        class StubDialog:
            def __init__(self, parent=None):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

            def values(self):
                return values

        monkeypatch.setattr(viewpoints_module, "AddCameraDialog", StubDialog)

    return install


def _row_text(table, row: int) -> list[str]:
    """Every cell in a row, as text. Fails loudly on an unfilled cell."""
    cells = [table.item(row, col) for col in range(table.columnCount())]
    assert all(cell is not None for cell in cells), f"row {row} has empty cells"
    return [cell.text() for cell in cells if cell is not None]


# -- The dialog itself -------------------------------------------------


def test_dialog_reports_what_was_entered(qapp):
    dialog = AddCameraDialog()
    dialog.position[0].setValue(1.5)
    dialog.position[1].setValue(-2.5)
    dialog.position[2].setValue(3.0)
    dialog.yaw.setValue(90.0)
    dialog.pitch.setValue(-30.0)

    assert dialog.values() == (1.5, -2.5, 3.0, 90.0, -30.0)


def test_dialog_reset_clears_every_field(qapp):
    dialog = AddCameraDialog()
    dialog.position[0].setValue(9.0)
    dialog.yaw.setValue(180.0)
    dialog.pitch.setValue(45.0)

    dialog.reset_button.click()

    assert dialog.values() == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_dialog_clamps_pitch_to_the_valid_range(qapp):
    """Pitch beyond +-90 has no meaning; the spin box must refuse it."""
    dialog = AddCameraDialog()

    dialog.pitch.setValue(120.0)
    assert dialog.pitch.value() == 90.0

    dialog.pitch.setValue(-120.0)
    assert dialog.pitch.value() == -90.0


# -- The store the button writes to ------------------------------------


def test_add_camera_appends_to_the_plan(loaded_store):
    before = loaded_store.camera_count

    loaded_store.add_camera((1.0, 2.0, 3.0), yaw=45.0, pitch=-10.0)

    plan = loaded_store.scene.plan
    assert loaded_store.camera_count == before + 1
    assert np.allclose(plan.positions[-1], [1.0, 2.0, 3.0])
    assert plan.yaws_deg[-1] == 45.0
    assert plan.pitches_deg[-1] == -10.0


def test_add_camera_mints_the_next_id(loaded_store):
    """Ids run vp1, vp2, ...; a new camera continues past the highest."""
    loaded_store.add_camera((0.0, 0.0, 0.0), yaw=0.0, pitch=0.0)
    assert loaded_store.scene.plan.ids[-1] == "vp3"

    loaded_store.add_camera((0.0, 0.0, 0.0), yaw=0.0, pitch=0.0)
    assert loaded_store.scene.plan.ids[-1] == "vp4"


def test_add_camera_leaves_the_existing_cameras_alone(loaded_store, sample_plan):
    loaded_store.add_camera((7.0, 7.0, 7.0), yaw=0.0, pitch=0.0)

    plan = loaded_store.scene.plan
    assert plan.ids[:2] == sample_plan.ids
    assert np.allclose(plan.positions[:2], sample_plan.positions)


def test_add_camera_announces_the_new_viewpoint(loaded_store, spy):
    watcher = spy(loaded_store.plan_changed)

    loaded_store.add_camera((1.0, 2.0, 3.0), yaw=45.0, pitch=-10.0)

    assert watcher.count == 1
    info = watcher.last
    assert isinstance(info, CameraInfo)
    assert info.index == 2  # appended after the two planned cameras
    assert np.allclose(info.position, [1.0, 2.0, 3.0])


def test_add_camera_without_a_scene_does_nothing(spy):
    """Nothing is loaded, so there is no plan to append to."""
    watcher = spy(SCENE_STORE.plan_changed)

    SCENE_STORE.add_camera((1.0, 2.0, 3.0), yaw=0.0, pitch=0.0)

    assert SCENE_STORE.scene is None
    assert watcher.count == 0


# -- The button -------------------------------------------------------


def test_button_click_spawns_a_camera(qapp, loaded_store, accepting_dialog):
    accepting_dialog(values=(4.0, 5.0, 6.0, 30.0, 15.0))
    panel = ViewpointsPanel()
    before = loaded_store.camera_count

    panel.button.click()

    assert loaded_store.camera_count == before + 1
    assert np.allclose(loaded_store.scene.plan.positions[-1], [4.0, 5.0, 6.0])


def test_button_click_adds_a_table_row(qapp, loaded_store, accepting_dialog):
    accepting_dialog(values=(4.0, 5.0, 6.0, 30.0, 15.0))
    panel = ViewpointsPanel()
    panel.refresh()
    before = panel.table.rowCount()

    panel.button.click()

    assert panel.table.rowCount() == before + 1
    assert _row_text(panel.table, before) == ["vp3", "4.0, 5.0, 6.0", "30.0", "15.0"]


def test_cancelling_the_dialog_spawns_nothing(qapp, loaded_store, accepting_dialog):
    accepting_dialog(accepted=False)
    panel = ViewpointsPanel()
    before = loaded_store.camera_count

    panel.button.click()

    assert loaded_store.camera_count == before


def test_button_click_without_a_scene_does_nothing(qapp, accepting_dialog):
    accepting_dialog()
    panel = ViewpointsPanel()

    panel.button.click()  # must not raise

    assert SCENE_STORE.scene is None


def test_spawning_does_not_re_emit_camera_picked(qapp, loaded_store, accepting_dialog, spy):
    """
    Refilling the table changes the selection, which would normally jump the
    viewport. `_suppress` exists to stop that; this pins it down.
    """
    accepting_dialog()
    panel = ViewpointsPanel()
    panel.refresh()

    watcher = spy(panel.camera_picked)
    panel.button.click()

    assert watcher.count == 0
