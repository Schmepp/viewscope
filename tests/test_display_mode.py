"""
Switching between the textured mesh and the target values.

The feature spans three pieces, tested separately:

* DisplayPanel turns a combo-box choice into a `mode_changed` signal.
* MeshView / TargetCloudView translate a mode into actor state.
* Viewport.set_mode wires the two together (GL, so marked).
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope.config import (
    MODE_ALL,
    MODE_GEOMETRY,
    MODE_TARGETS,
    MODE_TEXTURED,
    MODES,
)
from viewscope.DisplayPanel import DisplayPanel
from viewscope.scene import MeshView, TargetCloudView

# What each mode should show. Kept beside the tests so a new mode fails loudly.
MODE_VISIBILITY = [
    # mode,          mesh shown, targets shown
    (MODE_TEXTURED, True, False),
    (MODE_GEOMETRY, True, False),
    (MODE_TARGETS, False, True),
    (MODE_ALL, True, True),
]


# -- The panel that drives it -----------------------------------------


def test_panel_starts_on_all_three(qapp):
    """The combo box opens on the mode the viewport also defaults to."""
    panel = DisplayPanel()
    assert panel.mode.currentText() == MODE_ALL


def test_panel_offers_every_mode(qapp):
    panel = DisplayPanel()
    listed = [panel.mode.itemText(i) for i in range(panel.mode.count())]
    assert listed == MODES


@pytest.mark.parametrize("mode", MODES)
def test_panel_emits_mode_changed(qapp, spy, mode):
    """Choosing a mode tells the viewport, once, with the mode's name."""
    panel = DisplayPanel()
    watcher = spy(panel.mode_changed)

    panel.mode.setCurrentText(mode)

    if mode == MODE_ALL:  # already selected, so Qt emits nothing
        assert watcher.count == 0
    else:
        assert watcher.count == 1
        assert watcher.last == mode


def test_panel_does_not_re_emit_the_current_mode(qapp, spy):
    """Re-picking the selected mode must not churn the viewport."""
    panel = DisplayPanel()
    panel.mode.setCurrentText(MODE_TARGETS)

    watcher = spy(panel.mode_changed)
    panel.mode.setCurrentText(MODE_TARGETS)

    assert watcher.count == 0


# -- The views the mode drives ----------------------------------------


def test_mesh_view_hides_and_shows(sample_mesh):
    view = MeshView(sample_mesh)

    view.set_visible(False)
    assert view.actor.GetVisibility() == 0

    view.set_visible(True)
    assert view.actor.GetVisibility() == 1


def test_geometry_mode_draws_edges(sample_mesh):
    """Geometry is the wireframe-over-surface look; textured is not."""
    view = MeshView(sample_mesh)

    view.show_geometry()
    assert view.actor.GetProperty().GetEdgeVisibility() == 1

    view.show_textured()
    assert view.actor.GetProperty().GetEdgeVisibility() == 0


def test_textured_mode_uses_the_mesh_texture(sample_mesh):
    """A box has no image texture, so the actor must fall back to white."""
    view = MeshView(sample_mesh)
    view.show_textured()

    assert view.actor.GetProperty().GetColor() == (1.0, 1.0, 1.0)
    assert view.actor.GetMapper().GetScalarVisibility() == 1


def test_target_cloud_hides_and_shows():
    view = TargetCloudView(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]))

    view.set_visible(False)
    assert view.actor.GetVisibility() == 0

    view.set_visible(True)
    assert view.actor.GetVisibility() == 1


# -- The viewport that owns both --------------------------------------


@pytest.mark.gl
@pytest.mark.parametrize(("mode", "mesh_shown", "targets_shown"), MODE_VISIBILITY)
def test_set_mode_shows_the_right_actors(loaded_viewport, mode, mesh_shown, targets_shown):
    """The headline case: textured mesh <-> target values."""
    loaded_viewport.set_mode(mode)

    assert bool(loaded_viewport.mesh.actor.GetVisibility()) is mesh_shown
    assert bool(loaded_viewport.cloud.actor.GetVisibility()) is targets_shown


@pytest.mark.gl
def test_set_mode_round_trips(loaded_viewport):
    """Switching to targets and back restores the textured mesh."""
    loaded_viewport.set_mode(MODE_TARGETS)
    assert loaded_viewport.mesh.actor.GetVisibility() == 0

    loaded_viewport.set_mode(MODE_TEXTURED)
    assert loaded_viewport.mesh.actor.GetVisibility() == 1
    assert loaded_viewport.cloud.actor.GetVisibility() == 0


@pytest.mark.gl
def test_set_mode_before_a_scene_is_loaded_is_ignored(viewport):
    """No scene means no actors; set_mode must not raise or record the mode."""
    viewport.set_mode(MODE_TARGETS)

    assert viewport.has_scene is False
    assert viewport._mode == MODE_ALL


@pytest.mark.gl
def test_panel_signal_reaches_the_viewport(qapp, loaded_viewport):
    """The wiring MainWindow._connect sets up, exercised end to end."""
    panel = DisplayPanel()
    panel.mode_changed.connect(loaded_viewport.set_mode)

    panel.mode.setCurrentText(MODE_TARGETS)

    assert loaded_viewport.mesh.actor.GetVisibility() == 0
    assert loaded_viewport.cloud.actor.GetVisibility() == 1
