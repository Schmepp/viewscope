"""
The main viewport: everything except display mode and mouse rotation.

Those two have files of their own. This covers the rest of the surface
MainWindow drives -- scalar fields, point size, glyphs, occlusion, camera
navigation, the selection outline and the orientation widget.
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope.camera.structs import CameraInfo
from viewscope.scene import FieldStats

pytestmark = pytest.mark.gl


@pytest.fixture
def scored_viewport(viewport, scored_scene_data, loaded_store):
    """A viewport whose bundle has scores, so the field paths are live."""
    viewport.set_scene(scored_scene_data)
    return viewport


# -- Building the scene ------------------------------------------------


def test_a_fresh_viewport_has_no_scene(viewport):
    assert viewport.has_scene is False
    assert viewport.mesh is None
    assert viewport.cloud is None
    assert viewport.glyphs is None
    assert viewport.camera is None


def test_set_scene_builds_every_view(loaded_viewport, sample_plan):
    assert loaded_viewport.has_scene is True
    assert loaded_viewport.mesh is not None
    assert loaded_viewport.cloud is not None
    assert len(loaded_viewport.glyphs.actors) == len(sample_plan.ids)
    assert loaded_viewport.camera is not None


def test_set_scene_frames_the_model(loaded_viewport):
    """ResetCamera has to run, or the model opens off screen."""
    position = np.array(loaded_viewport.renderer.GetActiveCamera().GetPosition())

    assert np.isfinite(position).all()
    assert not np.allclose(position, 0.0)


def test_set_scene_saves_an_overview_to_return_to(loaded_viewport):
    assert loaded_viewport.camera._overview is not None


# -- Scalar field ------------------------------------------------------


def test_set_scalar_field_reports_stats(scored_viewport):
    stats = scored_viewport.set_scalar_field("score_8")

    assert isinstance(stats, FieldStats)
    assert stats.field == "score_8"


def test_set_scalar_field_without_a_scene_reports_nothing(viewport):
    assert viewport.set_scalar_field("score_8") is None


def test_set_scalar_field_on_an_unscored_bundle_reports_nothing(loaded_viewport):
    """The panel disables the combo box on this, so it must not raise."""
    assert loaded_viewport.set_scalar_field("score_8") is None


# -- Point size --------------------------------------------------------


def test_set_point_size_reaches_the_cloud(loaded_viewport):
    loaded_viewport.set_point_size(6)

    assert loaded_viewport.cloud.actor.GetProperty().GetPointSize() == pytest.approx(6.0)


def test_set_point_size_without_a_scene_is_ignored(viewport):
    viewport.set_point_size(6)  # must not raise


# -- Glyphs ------------------------------------------------------------


def test_set_glyphs_visible_hides_the_frusta(loaded_viewport):
    loaded_viewport.set_glyphs_visible(False)

    assert all(a.GetVisibility() == 0 for a in loaded_viewport.glyphs.actors)


def test_set_glyphs_visible_without_a_scene_is_ignored(viewport):
    viewport.set_glyphs_visible(False)  # must not raise


# -- Occlusion ---------------------------------------------------------


def test_an_occlusion_mask_repaints_the_cloud(scored_viewport):
    scored_viewport.set_scalar_field("score_8")

    scored_viewport.set_occlusion_mask(np.array([True, False, True]))

    assert scored_viewport.cloud.occluding is True


def test_clearing_the_mask_restores_the_field(scored_viewport):
    scored_viewport.set_scalar_field("score_8")
    scored_viewport.set_occlusion_mask(np.array([True, False, True]))

    scored_viewport.set_occlusion_mask(None)

    assert scored_viewport.cloud.occluding is False


def test_an_occlusion_mask_without_a_scene_is_ignored(viewport):
    viewport.set_occlusion_mask(np.array([True]))  # must not raise


# -- Camera navigation -------------------------------------------------


def test_show_camera_announces_the_move(loaded_viewport, spy):
    watcher = spy(loaded_viewport.camera_changed)

    loaded_viewport.show_camera(1)

    assert watcher.count == 1
    assert watcher.last.index == 1


def test_show_camera_hides_the_frustum_you_are_inside(loaded_viewport):
    loaded_viewport.show_camera(0)

    assert loaded_viewport.glyphs.actors[0].GetVisibility() == 0
    assert loaded_viewport.glyphs.actors[1].GetVisibility() == 1


def test_show_overview_announces_none(loaded_viewport, spy):
    """None is how the panels know the viewer is back in free look."""
    loaded_viewport.show_camera(0)
    watcher = spy(loaded_viewport.camera_changed)

    loaded_viewport.show_overview()

    assert watcher.count == 1
    assert watcher.last is None


def test_show_overview_brings_every_frustum_back(loaded_viewport):
    loaded_viewport.show_camera(0)

    loaded_viewport.show_overview()

    assert all(a.GetVisibility() == 1 for a in loaded_viewport.glyphs.actors)


def test_next_and_previous_walk_the_plan(loaded_viewport, spy):
    watcher = spy(loaded_viewport.camera_changed)

    loaded_viewport.next_camera()
    loaded_viewport.next_camera()
    loaded_viewport.prev_camera()

    assert [call[0].index for call in watcher.calls] == [0, 1, 0]


def test_navigation_without_a_scene_is_ignored(viewport, spy):
    watcher = spy(viewport.camera_changed)

    viewport.show_overview()
    viewport.show_camera(0)
    viewport.next_camera()
    viewport.prev_camera()

    assert watcher.count == 0


# -- The selection outline ---------------------------------------------


def test_selecting_a_camera_draws_an_outline(loaded_viewport):
    info = CameraInfo(index=0, position=np.array([3.0, 0.0, 0.0]), yaw=180.0, pitch=0.0)

    loaded_viewport.set_selected_camera_position(info)
    loaded_viewport.on_camera_changed()

    assert loaded_viewport.selected_camera_pos == (3.0, 0.0, 0.0)
    assert loaded_viewport.selected_outline.outline_actor is not None


def test_the_outline_moves_with_the_selection(loaded_viewport):
    first = CameraInfo(index=0, position=np.array([3.0, 0.0, 0.0]), yaw=0.0, pitch=0.0)
    second = CameraInfo(index=1, position=np.array([0.0, 3.0, 0.0]), yaw=0.0, pitch=0.0)

    loaded_viewport.set_selected_camera_position(first)
    loaded_viewport.on_camera_changed()
    loaded_viewport.set_selected_camera_position(second)
    loaded_viewport.on_camera_changed()

    assert loaded_viewport.selected_camera_pos == (0.0, 3.0, 0.0)
    assert loaded_viewport.selected_outline.outline_actor.GetCenter() == pytest.approx(
        (0.0, 3.0, 0.0)
    )


def test_the_overview_leaves_the_last_outline_in_place(loaded_viewport):
    """
    Worth knowing: set_selected_camera_position ignores None, so returning to
    the overview keeps the outline on whichever camera was last selected.
    """
    info = CameraInfo(index=0, position=np.array([3.0, 0.0, 0.0]), yaw=0.0, pitch=0.0)
    loaded_viewport.set_selected_camera_position(info)

    loaded_viewport.set_selected_camera_position(None)

    assert loaded_viewport.selected_camera_pos == (3.0, 0.0, 0.0)


def test_no_outline_is_drawn_before_a_camera_is_picked(loaded_viewport):
    loaded_viewport.on_camera_changed()

    assert loaded_viewport.selected_outline.outline_actor is None


def test_camera_changes_rebuild_the_glyphs_after_a_spawn(loaded_viewport, loaded_store):
    loaded_store.add_camera((1.0, 1.0, 1.0), yaw=0.0, pitch=0.0)

    loaded_viewport.on_camera_changed()

    assert len(loaded_viewport.glyphs.actors) == 3


def test_camera_changes_without_a_scene_are_ignored(viewport):
    viewport.on_camera_changed()  # must not raise

    assert viewport.glyphs is None


# -- The orientation widget --------------------------------------------


def test_the_orientation_widget_starts_on(viewport):
    assert viewport.orientation_widget.GetEnabled() == 1


def test_toggling_the_orientation_widget(viewport):
    viewport.toggle_camera_orientation_visible()
    assert viewport.orientation_widget.GetEnabled() == 0

    viewport.toggle_camera_orientation_visible()
    assert viewport.orientation_widget.GetEnabled() == 1


def test_setting_the_orientation_widget_directly(viewport):
    viewport.set_camera_orientation_visible(False)

    assert viewport.orientation_widget.GetEnabled() == 0
