"""
The 90-degree rotate-left / rotate-right buttons.

NOTE: this feature does not exist yet. Nothing on any branch orbits the camera,
and MainWindow._build_actions builds only Previous / Next / Overview / Toggle
Orientation. These tests are the spec for it, written against the smallest API
that makes the behaviour testable:

    # src/viewscope/config.py
    ROTATE_STEP_DEG = 90.0

    # src/viewscope/viewport.py
    def rotate_view(self, degrees: float):
        \"\"\"Orbit the camera around the model, keeping the focal point fixed.\"\"\"
        if not self.has_scene:
            return
        camera = self.renderer.GetActiveCamera()
        camera.Azimuth(degrees)
        camera.OrthogonalizeViewUp()
        self.renderer.ResetCameraClippingRange()
        self.render()

    def rotate_left(self):
        self.rotate_view(ROTATE_STEP_DEG)

    def rotate_right(self):
        self.rotate_view(-ROTATE_STEP_DEG)

    # src/viewscope/window.py, in _build_actions
    self.act_rotate_left = QAction("Rotate Left", self)
    self.act_rotate_left.setShortcut(QKeySequence("["))
    self.act_rotate_left.triggered.connect(self.viewport.rotate_left)

    self.act_rotate_right = QAction("Rotate Right", self)
    self.act_rotate_right.setShortcut(QKeySequence("]"))
    self.act_rotate_right.triggered.connect(self.viewport.rotate_right)

Drop that in, delete the `pytestmark` line below, and these run.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.skip(reason="rotate_view() is not implemented yet; see this docstring")

ROTATE_STEP_DEG = 90.0


def _camera_state(viewport):
    camera = viewport.renderer.GetActiveCamera()
    return (
        np.array(camera.GetPosition()),
        np.array(camera.GetFocalPoint()),
        np.array(camera.GetViewUp()),
    )


@pytest.mark.gl
def test_rotate_left_moves_the_camera(loaded_viewport):
    before, _, _ = _camera_state(loaded_viewport)

    loaded_viewport.rotate_left()

    after, _, _ = _camera_state(loaded_viewport)
    assert not np.allclose(before, after)


@pytest.mark.gl
def test_four_rotations_return_to_the_start(loaded_viewport):
    """90 degrees, four times, is a full turn."""
    before, _, _ = _camera_state(loaded_viewport)

    for _ in range(4):
        loaded_viewport.rotate_left()

    after, _, _ = _camera_state(loaded_viewport)
    assert np.allclose(before, after, atol=1e-6)


@pytest.mark.gl
def test_left_then_right_is_a_no_op(loaded_viewport):
    before, _, _ = _camera_state(loaded_viewport)

    loaded_viewport.rotate_left()
    loaded_viewport.rotate_right()

    after, _, _ = _camera_state(loaded_viewport)
    assert np.allclose(before, after, atol=1e-6)


@pytest.mark.gl
def test_rotation_orbits_rather_than_flies_away(loaded_viewport):
    """The camera circles the model: the focal point and radius must hold."""
    position, focal, _ = _camera_state(loaded_viewport)
    radius = np.linalg.norm(position - focal)

    loaded_viewport.rotate_left()

    new_position, new_focal, _ = _camera_state(loaded_viewport)
    assert np.allclose(focal, new_focal, atol=1e-6)
    assert np.isclose(np.linalg.norm(new_position - new_focal), radius, atol=1e-6)


@pytest.mark.gl
def test_rotation_turns_the_expected_way(loaded_viewport):
    """
    Left is counter-clockwise seen from +Z, so a camera on +X ends up on +Y.

    Pinned with an explicit angle rather than a coordinate, so the test still
    reads correctly if the overview camera moves.
    """
    position, focal, _ = _camera_state(loaded_viewport)
    start = np.arctan2(*(position - focal)[[1, 0]])

    loaded_viewport.rotate_left()

    position, focal, _ = _camera_state(loaded_viewport)
    end = np.arctan2(*(position - focal)[[1, 0]])

    turned = np.degrees((end - start + np.pi) % (2 * np.pi) - np.pi)
    assert np.isclose(turned, ROTATE_STEP_DEG, atol=1e-6)


@pytest.mark.gl
def test_rotation_keeps_the_view_up_upright(loaded_viewport):
    """OrthogonalizeViewUp stops the horizon drifting over repeated presses."""
    for _ in range(3):
        loaded_viewport.rotate_left()

    _, _, up = _camera_state(loaded_viewport)
    assert np.isclose(np.linalg.norm(up), 1.0, atol=1e-6)
    assert up[2] > 0.0


@pytest.mark.gl
def test_rotation_before_a_scene_is_loaded_is_ignored(viewport):
    viewport.rotate_left()  # must not raise
    assert viewport.has_scene is False


@pytest.mark.gl
def test_rotation_does_not_disturb_the_display_mode(loaded_viewport):
    from viewscope.config import MODE_TARGETS

    loaded_viewport.set_mode(MODE_TARGETS)
    loaded_viewport.rotate_left()

    assert loaded_viewport.mesh.actor.GetVisibility() == 0
    assert loaded_viewport.cloud.actor.GetVisibility() == 1


# -- The buttons -------------------------------------------------------


@pytest.mark.gl
def test_the_toolbar_actions_are_wired(qapp, monkeypatch):
    """Each button calls rotate_view once, with the right sign."""
    from viewscope.viewport import Viewport
    from viewscope.window import MainWindow

    calls = []
    monkeypatch.setattr(Viewport, "rotate_view", lambda self, deg: calls.append(deg))

    window = MainWindow()
    try:
        # Looked up by name, not attribute access: the actions do not exist
        # until the feature lands, and `ty` checks this file today.
        for name in ("act_rotate_left", "act_rotate_right"):
            getattr(window, name).trigger()
    finally:
        window.close()

    assert calls == [ROTATE_STEP_DEG, -ROTATE_STEP_DEG]
