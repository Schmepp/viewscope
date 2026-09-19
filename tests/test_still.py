"""Unit tests for the exported still in src/viewscope/CameraViewport.py.

Only the sizing is exercised here. Shooting a still needs a GL context and a
window on screen, which is the one thing a unit test cannot have; what it can
check is that the tile count asked for matches the pixels wanted.
"""

import pytest

from viewscope.camera_viewport import still_scale
from viewscope.config import STILL_MAX_SCALE, STILL_WIDTH

# -----------------------------------------------------------------------------
# How far the view is blown up
# -----------------------------------------------------------------------------


def test_a_dock_narrower_than_the_still_is_blown_up():
    assert still_scale(960, 3840) == 4


def test_a_part_tile_is_rounded_up_so_the_width_is_a_floor():
    """1000 x 3 clears 2560; 1000 x 2 would not."""
    assert still_scale(1000, 2560) == 3


def test_a_view_already_wide_enough_is_shot_as_it_is():
    assert still_scale(4000, STILL_WIDTH) == 1


@pytest.mark.parametrize("shown", [0, -5])
def test_a_view_with_no_size_yet_asks_for_one_tile(shown):
    """A dock closed or not yet laid out must not divide by nothing."""
    assert still_scale(shown, STILL_WIDTH) == 1


def test_a_dock_dragged_narrow_stops_at_the_ceiling():
    assert still_scale(10, STILL_WIDTH) == STILL_MAX_SCALE


def test_the_default_width_is_worth_exporting():
    """The point of the button: more pixels than any dock is shown at."""
    assert STILL_WIDTH >= 3840
