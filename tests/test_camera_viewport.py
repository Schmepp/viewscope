"""
The first-person viewport docked on the right.

It mirrors most of Viewport's API but with the interactor disabled -- it is a
preview of what a planned camera sees, not something the user flies. It also
has no orientation widget and no mouse lock.
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope.CameraViewport import CameraViewport
from viewscope.config import MODE_ALL, MODE_GEOMETRY, MODE_TARGETS, MODE_TEXTURED
from viewscope.scene import FieldStats

pytestmark = pytest.mark.gl


@pytest.fixture
def fpv(qapp):
    widget = CameraViewport()
    yield widget
    widget.renderer.RemoveAllViewProps()
    widget.shutdown()


@pytest.fixture
def loaded_fpv(fpv, scene_data, loaded_store):
    fpv.set_scene(scene_data)
    return fpv


@pytest.fixture
def scored_fpv(fpv, scored_scene_data, loaded_store):
    fpv.set_scene(scored_scene_data)
    return fpv


# -- Lifecycle ---------------------------------------------------------


def test_a_fresh_viewport_has_no_scene(fpv):
    assert fpv.has_scene is False


def test_set_scene_builds_every_view(loaded_fpv, sample_plan):
    assert loaded_fpv.has_scene is True
    assert loaded_fpv.mesh is not None
    assert loaded_fpv.cloud is not None
    assert len(loaded_fpv.glyphs.actors) == len(sample_plan.ids)


def test_starting_disables_the_interactor(loaded_fpv):
    """
    This is the point of the widget: the preview must not be draggable, or the
    view stops matching the camera it is supposed to be showing.
    """
    loaded_fpv.start()

    assert loaded_fpv._interactor.GetEnabled() == 0


# -- Display state -----------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "mesh_shown", "targets_shown"),
    [
        (MODE_TEXTURED, True, False),
        (MODE_GEOMETRY, True, False),
        (MODE_TARGETS, False, True),
        (MODE_ALL, True, True),
    ],
)
def test_set_mode_shows_the_right_actors(loaded_fpv, mode, mesh_shown, targets_shown):
    loaded_fpv.set_mode(mode)

    assert bool(loaded_fpv.mesh.actor.GetVisibility()) is mesh_shown
    assert bool(loaded_fpv.cloud.actor.GetVisibility()) is targets_shown


def test_geometry_mode_draws_edges(loaded_fpv):
    loaded_fpv.set_mode(MODE_GEOMETRY)

    assert loaded_fpv.mesh.actor.GetProperty().GetEdgeVisibility() == 1


def test_set_mode_before_a_scene_is_ignored(fpv):
    fpv.set_mode(MODE_TARGETS)

    assert fpv._mode == MODE_ALL


def test_set_scalar_field_reports_stats(scored_fpv):
    assert isinstance(scored_fpv.set_scalar_field("score_4"), FieldStats)


def test_set_scalar_field_without_a_scene_reports_nothing(fpv):
    assert fpv.set_scalar_field("score_4") is None


def test_set_point_size_reaches_the_cloud(loaded_fpv):
    loaded_fpv.set_point_size(5)

    assert loaded_fpv.cloud.actor.GetProperty().GetPointSize() == pytest.approx(5.0)


def test_set_point_size_without_a_scene_is_ignored(fpv):
    fpv.set_point_size(5)  # must not raise


def test_set_glyphs_visible_hides_the_frusta(loaded_fpv):
    loaded_fpv.set_glyphs_visible(False)

    assert all(a.GetVisibility() == 0 for a in loaded_fpv.glyphs.actors)


def test_set_glyphs_visible_without_a_scene_is_ignored(fpv):
    fpv.set_glyphs_visible(False)  # must not raise


def test_occlusion_repaints_the_cloud(scored_fpv):
    scored_fpv.set_occlusion_mask(np.array([True, False, True]))

    assert scored_fpv.cloud.occluding is True


def test_occlusion_without_a_scene_is_ignored(fpv):
    fpv.set_occlusion_mask(np.array([True]))  # must not raise


# -- Camera navigation -------------------------------------------------


def test_show_camera_flies_to_the_viewpoint(loaded_fpv, sample_plan, spy):
    watcher = spy(loaded_fpv.camera_changed)

    loaded_fpv.show_camera(1)

    assert watcher.last.index == 1
    assert np.allclose(
        loaded_fpv.renderer.GetActiveCamera().GetPosition(), sample_plan.positions[1]
    )


def test_show_camera_hides_the_frustum_you_are_looking_through(loaded_fpv):
    loaded_fpv.show_camera(0)

    assert loaded_fpv.glyphs.actors[0].GetVisibility() == 0


def test_show_overview_announces_none(loaded_fpv, spy):
    loaded_fpv.show_camera(0)
    watcher = spy(loaded_fpv.camera_changed)

    loaded_fpv.show_overview()

    assert watcher.last is None


def test_next_and_previous_walk_the_plan(loaded_fpv, spy):
    watcher = spy(loaded_fpv.camera_changed)

    loaded_fpv.next_camera()
    loaded_fpv.next_camera()
    loaded_fpv.prev_camera()

    assert [call[0].index for call in watcher.calls] == [0, 1, 0]


def test_navigation_without_a_scene_is_ignored(fpv, spy):
    watcher = spy(fpv.camera_changed)

    fpv.show_overview()
    fpv.show_camera(0)
    fpv.next_camera()
    fpv.prev_camera()

    assert watcher.count == 0


# -- Reacting to a spawned camera --------------------------------------


def test_a_spawned_camera_gets_a_frustum(loaded_fpv, loaded_store):
    loaded_store.add_camera((1.0, 1.0, 1.0), yaw=0.0, pitch=0.0)

    loaded_fpv.on_camera_changed()

    assert len(loaded_fpv.glyphs.actors) == 3


def test_camera_changes_without_a_scene_are_ignored(fpv):
    fpv.on_camera_changed()  # must not raise

    assert fpv.glyphs is None


def test_rebuilding_resets_the_camera(loaded_fpv, loaded_store):
    """
    Pins the known bug: on_camera_changed rebuilds the CameraController and
    calls ResetCamera, so spawning a camera throws the preview back to the
    overview instead of holding the selected viewpoint. See the TODO in
    window.py -- this is why the call is commented out there.
    """
    loaded_fpv.show_camera(1)
    at_viewpoint = np.array(loaded_fpv.renderer.GetActiveCamera().GetPosition())

    loaded_store.add_camera((1.0, 1.0, 1.0), yaw=0.0, pitch=0.0)
    loaded_fpv.on_camera_changed()

    after = np.array(loaded_fpv.renderer.GetActiveCamera().GetPosition())
    assert not np.allclose(at_viewpoint, after)
    assert loaded_fpv.camera.index is None
