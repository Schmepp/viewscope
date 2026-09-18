"""Unit tests for the camera frustums in src/viewscope/scene/gizmos.py.

Actors only: building a CameraGlyphs needs no render window, so what each
frustum is told to wear can be read straight off its properties.
"""

import numpy as np
import pytest

import viewscope_core as vc
from viewscope.config import (
    GLYPH_SOLID_OPACITY,
    GLYPH_WIREFRAME_OPACITY,
    ROUTE_SELECTED_COLOUR,
    ROUTE_UNSELECTED_COLOUR,
)
from viewscope.scene.gizmos import CameraGlyphs


@pytest.fixture
def plan():
    """Four viewpoints, which is enough to have some in a route and some out."""
    return vc.Plan(
        camera={"width": 1368, "height": 912, "yfov_deg": 53.13},
        ids=("vp000", "vp001", "vp002", "vp003"),
        positions=np.array([[0.0, 0.0, 5.0], [1.0, 0.0, 5.0], [2.0, 0.0, 5.0], [3.0, 0.0, 5.0]]),
        yaws_deg=np.array([0.0, 90.0, 180.0, -90.0]),
        pitches_deg=np.array([-10.0, -20.0, -30.0, -40.0]),
    )


def glyph(glyphs: CameraGlyphs, index: int):
    """The actor drawing one camera, by its row in the plan."""
    return next(actor for actor, row in glyphs.glyphs.items() if row == index)


def worn(glyphs: CameraGlyphs, index: int):
    """What that camera is wearing: representation, opacity and colour."""
    prop = glyph(glyphs, index).GetProperty()

    return prop.GetRepresentationAsString(), prop.GetOpacity(), prop.GetColor()


# -----------------------------------------------------------------------------
# How solid a frustum is drawn
# -----------------------------------------------------------------------------


def test_a_wireframe_frustum_is_drawn_exactly_as_it_always_was(plan):
    """The wireframe is the one people read the scene by; it does not move."""
    glyphs = CameraGlyphs(plan)
    glyphs.wireframe_enabled = True
    glyphs._refresh()

    representation, opacity, _ = worn(glyphs, 0)

    assert representation == "Wireframe"
    assert opacity == pytest.approx(GLYPH_WIREFRAME_OPACITY)
    assert GLYPH_WIREFRAME_OPACITY == 0.2, "the value wireframes have always worn"


def test_a_solid_frustum_is_drawn_strongly_enough_to_make_out(plan):
    """Filled in, a frustum needs far more than a wireframe to read at all."""
    glyphs = CameraGlyphs(plan)
    glyphs.wireframe_enabled = False
    glyphs._refresh()

    representation, opacity, _ = worn(glyphs, 0)

    assert representation == "Surface"
    assert opacity == pytest.approx(GLYPH_SOLID_OPACITY)
    assert GLYPH_SOLID_OPACITY > GLYPH_WIREFRAME_OPACITY


def test_the_two_representations_do_not_share_an_opacity(plan):
    """One number for both is what left the solid frustums a smudge."""
    assert GLYPH_SOLID_OPACITY != GLYPH_WIREFRAME_OPACITY


def test_the_camera_being_looked_at_is_drawn_solid_whatever_the_mode(plan):
    for wireframe in (True, False):
        glyphs = CameraGlyphs(plan)
        glyphs.wireframe_enabled = wireframe
        glyphs.set_selected(2)

        representation, opacity, _ = worn(glyphs, 2)

        assert representation == "Surface"
        assert opacity == pytest.approx(1.0)


# -----------------------------------------------------------------------------
# What a frustum wears
# -----------------------------------------------------------------------------


def test_a_camera_in_the_route_wears_cyan(plan):
    glyphs = CameraGlyphs(plan)
    glyphs.set_route({0, 2})

    _, _, colour = worn(glyphs, 0)
    red, green, blue = colour

    assert colour == pytest.approx(ROUTE_SELECTED_COLOUR)
    assert green > 0.7 and blue > 0.7, "cyan is green and blue together"
    assert red < 0.3, "and very little red"


def test_a_camera_taken_out_of_the_route_stays_grey(plan):
    glyphs = CameraGlyphs(plan)
    glyphs.set_route({0, 2})

    _, _, colour = worn(glyphs, 1)

    assert colour == pytest.approx(ROUTE_UNSELECTED_COLOUR)


def test_the_route_colours_tell_each_other_apart(plan):
    """In and out of the route has to be readable at a glance, not squinted at."""
    apart = np.abs(np.array(ROUTE_SELECTED_COLOUR) - np.array(ROUTE_UNSELECTED_COLOUR))

    assert apart.max() > 0.5


def test_the_camera_being_looked_at_outranks_the_route(plan):
    """Gold wins: it says where you are, which the route colour does not."""
    glyphs = CameraGlyphs(plan)
    glyphs.set_route({0, 2})
    glyphs.set_selected(0)

    _, _, colour = worn(glyphs, 0)

    assert colour == pytest.approx(CameraGlyphs.COLOUR_ACTIVE)
