"""
The views drawn into the viewport: mesh, target cloud, frusta, selection outline.

None of these touch Qt, and none of them render until the viewport asks, so
they can be driven against a bare vtkRenderer with no GL context.
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope.config import OCCLUDED_COLOUR, VISIBLE_COLOUR
from viewscope.scene import CameraGlyphs, CameraOutline, FieldStats, MeshView, TargetCloudView

TARGETS = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


@pytest.fixture
def cloud(sample_scores):
    return TargetCloudView(TARGETS, sample_scores)


# -- MeshView ----------------------------------------------------------


def test_mesh_view_registers_its_actor(sample_mesh, renderer):
    MeshView(sample_mesh).add_to(renderer)

    assert renderer.GetActors().GetNumberOfItems() == 1


def test_geometry_mode_uses_the_flat_colour(sample_mesh):
    from viewscope.config import GEOMETRY_COLOUR

    view = MeshView(sample_mesh)
    view.show_geometry()

    assert view.actor.GetProperty().GetColor() == pytest.approx(GEOMETRY_COLOUR)
    assert view.actor.GetMapper().GetScalarVisibility() == 0


def test_switching_back_to_textured_drops_the_flat_colour(sample_mesh):
    view = MeshView(sample_mesh)
    view.show_geometry()

    view.show_textured()

    assert view.actor.GetProperty().GetColor() == (1.0, 1.0, 1.0)
    assert view.actor.GetMapper().GetScalarVisibility() == 1


# -- TargetCloudView, unscored -----------------------------------------


def test_an_unscored_cloud_has_no_scalar_bar():
    """Without scores there is nothing for a colour legend to explain."""
    view = TargetCloudView(TARGETS)

    assert view.has_scores is False
    assert view.scalar_bar is None
    assert view.lut is None


def test_setting_a_field_on_an_unscored_cloud_returns_nothing():
    view = TargetCloudView(TARGETS)

    assert view.set_field("score_8") is None


def test_an_unscored_cloud_still_hides_and_shows():
    view = TargetCloudView(TARGETS)

    view.set_visible(False)

    assert view.actor.GetVisibility() == 0


def test_point_size_reaches_the_actor():
    view = TargetCloudView(TARGETS)

    view.set_point_size(7)

    assert view.actor.GetProperty().GetPointSize() == pytest.approx(7.0)


# -- TargetCloudView, scored -------------------------------------------


def test_a_scored_cloud_gets_a_scalar_bar(cloud, renderer):
    assert cloud.has_scores is True
    assert cloud.scalar_bar is not None

    cloud.add_to(renderer)

    assert renderer.GetActors2D().GetNumberOfItems() == 1


def test_set_field_reports_the_stats(cloud):
    stats = cloud.set_field("score_8")

    assert isinstance(stats, FieldStats)
    assert stats.field == "score_8"
    assert stats.minimum == pytest.approx(0.0)
    assert stats.mean == pytest.approx(0.5)
    assert stats.maximum == pytest.approx(1.0)


def test_set_field_colours_by_that_field(cloud):
    cloud.set_field("diversity_8")

    scalars = cloud.polydata.GetPointData().GetScalars()
    assert scalars.GetName() == "diversity_8"
    assert cloud.actor.GetMapper().GetScalarRange() == pytest.approx((0.10, 0.30))


def test_set_field_titles_the_scalar_bar(cloud):
    cloud.set_field("score_4")

    assert cloud.scalar_bar.GetTitle() == "score_4"


def test_switching_field_rescales_the_colours(cloud):
    cloud.set_field("score_8")

    cloud.set_field("score_4")

    assert cloud.actor.GetMapper().GetScalarRange() == pytest.approx((0.25, 0.75))


def test_hiding_a_scored_cloud_hides_its_legend(cloud):
    cloud.set_visible(False)

    assert cloud.scalar_bar.GetVisibility() == 0


# -- Occlusion colouring -----------------------------------------------


def test_occlusion_repaints_the_cloud(cloud):
    cloud.set_field("score_8")

    cloud.set_occlusion(np.array([True, False, True]))

    assert cloud.occluding is True
    assert cloud.polydata.GetPointData().GetScalars().GetName() == "visible"
    assert cloud.actor.GetMapper().GetScalarRange() == pytest.approx((0.0, 1.0))


def test_occlusion_uses_the_visible_and_occluded_colours(cloud):
    cloud.set_occlusion(np.array([True, False, True]))

    lut = cloud.actor.GetMapper().GetLookupTable()
    # VTK stores table colours as 8-bit, so allow one quantisation step.
    assert lut.GetTableValue(0)[:3] == pytest.approx(OCCLUDED_COLOUR, abs=1 / 255)
    assert lut.GetTableValue(1)[:3] == pytest.approx(VISIBLE_COLOUR, abs=1 / 255)


def test_occlusion_hides_the_scalar_bar(cloud):
    """The legend explains the field, which is not what is on screen."""
    cloud.set_field("score_8")

    cloud.set_occlusion(np.array([True, False, True]))

    assert cloud.scalar_bar.GetVisibility() == 0


def test_clearing_occlusion_restores_the_field(cloud):
    cloud.set_field("diversity_4")
    cloud.set_occlusion(np.array([True, False, True]))

    cloud.set_occlusion(None)

    assert cloud.occluding is False
    assert cloud.polydata.GetPointData().GetScalars().GetName() == "diversity_4"
    assert cloud.actor.GetMapper().GetScalarRange() == pytest.approx((0.15, 0.35))
    assert cloud.scalar_bar.GetVisibility() == 1


def test_clearing_occlusion_before_any_field_just_stops_colouring(cloud):
    cloud.set_occlusion(np.array([True, False, True]))

    cloud.set_occlusion(None)

    assert cloud.actor.GetMapper().GetScalarVisibility() == 0


def test_changing_field_while_occluded_does_not_repaint(cloud):
    """
    The panel keeps working while occlusion is on; the new field is remembered
    but must not steal the scalars back until occlusion is turned off.
    """
    cloud.set_field("score_8")
    cloud.set_occlusion(np.array([True, False, True]))

    stats = cloud.set_field("score_4")

    assert stats.field == "score_4"  # the panel still gets its numbers
    assert cloud.polydata.GetPointData().GetScalars().GetName() == "visible"

    cloud.set_occlusion(None)
    assert cloud.polydata.GetPointData().GetScalars().GetName() == "score_4"


def test_an_occluded_cloud_shown_again_keeps_its_legend_hidden(cloud):
    cloud.set_field("score_8")
    cloud.set_occlusion(np.array([True, False, True]))

    cloud.set_visible(True)

    assert cloud.actor.GetVisibility() == 1
    assert cloud.scalar_bar.GetVisibility() == 0


# -- CameraGlyphs ------------------------------------------------------


def test_one_glyph_per_planned_camera(sample_plan, renderer):
    glyphs = CameraGlyphs(sample_plan)
    glyphs.add_to(renderer)

    assert len(glyphs.actors) == len(sample_plan.ids)
    assert renderer.GetActors().GetNumberOfItems() == len(sample_plan.ids)


def test_glyphs_hide_together(sample_plan):
    glyphs = CameraGlyphs(sample_plan)

    glyphs.set_visible(False)

    assert [a.GetVisibility() for a in glyphs.actors] == [0, 0]


def test_the_active_frustum_is_hidden(sample_plan):
    """You are sitting inside it; drawn, it would fill the whole view."""
    glyphs = CameraGlyphs(sample_plan)

    glyphs.set_active(0)

    assert glyphs.actors[0].GetVisibility() == 0
    assert glyphs.actors[1].GetVisibility() == 1


def test_leaving_a_camera_brings_its_frustum_back(sample_plan):
    glyphs = CameraGlyphs(sample_plan)
    glyphs.set_active(0)

    glyphs.set_active(None)

    assert [a.GetVisibility() for a in glyphs.actors] == [1, 1]


def test_hidden_glyphs_stay_hidden_when_the_camera_changes(sample_plan):
    glyphs = CameraGlyphs(sample_plan)
    glyphs.set_visible(False)

    glyphs.set_active(1)

    assert [a.GetVisibility() for a in glyphs.actors] == [0, 0]


# -- CameraOutline -----------------------------------------------------


def test_the_outline_appears_at_the_camera(renderer):
    outline = CameraOutline()

    outline.build(renderer, (1.0, 2.0, 3.0))

    actor = outline.outline_actor
    assert actor is not None
    assert renderer.GetActors().GetNumberOfItems() == 1
    assert actor.GetCenter() == pytest.approx((1.0, 2.0, 3.0))


def test_removing_the_outline_clears_the_renderer(renderer):
    outline = CameraOutline()
    outline.build(renderer, (0.0, 0.0, 0.0))

    outline.remove(renderer)

    assert outline.outline_actor is None
    assert renderer.GetActors().GetNumberOfItems() == 0


def test_removing_an_outline_that_was_never_built_is_harmless(renderer):
    """window.py removes before it builds on every camera change."""
    CameraOutline().remove(renderer)

    assert renderer.GetActors().GetNumberOfItems() == 0


def test_rebuilding_the_outline_moves_it(renderer):
    outline = CameraOutline()
    outline.build(renderer, (0.0, 0.0, 0.0))

    outline.remove(renderer)
    outline.build(renderer, (5.0, 5.0, 5.0))

    actor = outline.outline_actor
    assert actor is not None
    assert renderer.GetActors().GetNumberOfItems() == 1
    assert actor.GetCenter() == pytest.approx((5.0, 5.0, 5.0))
