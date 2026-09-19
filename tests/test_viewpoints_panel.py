"""Unit tests for src/viewscope/panels/viewpoints_panel.py.

The panel end of adding a camera: the button now asks how, rather than going
straight to the dialog it always used. What happens after the clicks is the
viewport's, and is exercised against a real render window instead.
"""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

import viewscope_core as vc
from viewscope.panels import ViewpointsPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    return ViewpointsPanel()


# -----------------------------------------------------------------------------
# The button asks how
# -----------------------------------------------------------------------------


def test_the_button_offers_both_ways_of_saying_where(panel):
    assert [action.text() for action in panel.menu.actions()] == [
        "Enter co-ordinates...",
        "Place in the view",
    ]


def test_the_button_opens_the_menu_rather_than_a_dialog(panel):
    """Clicking it must not go straight to the one it always used to."""
    assert panel.button.menu() is panel.menu


def test_placing_in_the_view_is_asked_for_and_not_done_here(panel):
    """The panel has no viewport; all it can do is say that this is wanted."""
    asked = []
    panel.place_requested.connect(lambda: asked.append(True))

    panel.place_action.trigger()

    assert asked == [True]


def test_entering_co_ordinates_does_nothing_without_a_scene(panel, monkeypatch):
    """No scene, no dialog: there is nothing for a camera to be added to."""

    class NoScene:
        scene = None

    monkeypatch.setattr("viewscope.panels.viewpoints_panel.SCENE_STORE", NoScene())
    monkeypatch.setattr(
        "viewscope.panels.viewpoints_panel.AddCameraDialog",
        lambda parent: pytest.fail("a dialog was opened with no scene to add to"),
    )

    panel._on_button_add_camera_clicked()


# -----------------------------------------------------------------------------
# What the two clicks are turned into
# -----------------------------------------------------------------------------


def test_a_camera_faces_the_point_it_was_aimed_at():
    """The angles the viewport hands over are the ones that look at click two."""
    standpoint = np.array([10.0, 0.0, 5.0])
    target = np.array([0.0, 0.0, 0.0])

    yaw, pitch = vc.look_at_angles(standpoint, target)

    assert yaw == pytest.approx(180.0)
    assert pitch < 0.0, "looking down at something below it"


def test_standing_off_the_surface_is_what_keeps_a_camera_out_of_the_model():
    """The first click is a point on the model; the camera goes out along it."""
    surface = np.array([1.0, 2.0, 3.0])
    outward = np.array([0.0, 0.0, 1.0])

    standpoint = surface + outward * vc.constants.MU_RHO_M

    assert np.linalg.norm(standpoint - surface) == pytest.approx(vc.constants.MU_RHO_M)
    assert vc.look_at_angles(standpoint, surface)[1] == pytest.approx(-90.0)
