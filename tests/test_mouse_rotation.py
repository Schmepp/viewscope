"""
Rotating the model by dragging on the trackpad.

This is the rotation users actually have: vtkInteractorStyleTrackballCamera
orbits the camera, and Viewport wraps it in a mouse lock so a drag never runs
out of screen. The lock is the fiddly part -- it hides the pointer, warps it
back to where the drag started after every move, and keeps a separate virtual
position that grows without bound.

The pointer warp is stubbed by `fake_cursor`; a real QCursor.setPos would
yank the mouse of whoever is running the tests.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt

from tests.conftest import mouse_move, mouse_press, mouse_release

pytestmark = pytest.mark.gl

ANCHOR = QPoint(200, 150)


def _camera(viewport):
    cam = viewport.renderer.GetActiveCamera()
    return np.array(cam.GetPosition()), np.array(cam.GetFocalPoint())


# -- Taking and releasing the lock -------------------------------------


@pytest.mark.parametrize(
    "button",
    [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton],
)
def test_every_drag_button_takes_the_lock(dragging_viewport, button):
    assert dragging_viewport._mouse_locked is False

    dragging_viewport.mousePressEvent(mouse_press(200, 150, button))

    assert dragging_viewport._mouse_locked is True
    assert dragging_viewport._mouse_lock_global_pos == ANCHOR
    assert dragging_viewport._mouse_virtual_local_pos == ANCHOR


def test_releasing_the_last_button_frees_the_lock(dragging_viewport):
    dragging_viewport.mousePressEvent(mouse_press(200, 150))

    dragging_viewport.mouseReleaseEvent(mouse_release(200, 150))

    assert dragging_viewport._mouse_locked is False


def test_the_lock_holds_while_another_button_is_down(dragging_viewport):
    """Letting go of the left button mid-drag must not end a right-drag."""
    dragging_viewport.mousePressEvent(mouse_press(200, 150))

    dragging_viewport.mouseReleaseEvent(
        mouse_release(200, 150, still_held=Qt.MouseButton.MiddleButton)
    )

    assert dragging_viewport._mouse_locked is True


def test_a_second_press_keeps_the_original_anchor(dragging_viewport):
    """Chording a second button must not move the point the drag pivots on."""
    dragging_viewport.mousePressEvent(mouse_press(200, 150))

    dragging_viewport.mousePressEvent(mouse_press(300, 250, Qt.MouseButton.RightButton))

    assert dragging_viewport._mouse_lock_global_pos == ANCHOR


def test_releasing_restores_the_pointer_to_the_anchor(dragging_viewport, fake_cursor):
    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    fake_cursor.clear()

    dragging_viewport.mouseReleaseEvent(mouse_release(200, 150))

    assert fake_cursor == [ANCHOR]


# -- What the drag does to the camera ----------------------------------


def test_dragging_rotates_the_camera(dragging_viewport):
    before, _ = _camera(dragging_viewport)

    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))

    after, _ = _camera(dragging_viewport)
    assert not np.allclose(before, after)


def test_dragging_orbits_rather_than_flies_away(dragging_viewport):
    """
    The trackball style pivots around the focal point.

    This is the invariant the 90-degree buttons would also need to hold, which
    is why it is pinned here rather than left to VTK.
    """
    position, focal = _camera(dragging_viewport)
    radius = np.linalg.norm(position - focal)

    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))

    new_position, new_focal = _camera(dragging_viewport)
    assert np.allclose(focal, new_focal, atol=1e-9)
    assert np.isclose(np.linalg.norm(new_position - new_focal), radius, atol=1e-6)


def test_dragging_back_returns_to_the_start(dragging_viewport):
    """Right then left by the same amount is a round trip."""
    before, _ = _camera(dragging_viewport)

    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))
    dragging_viewport._ignore_next_mouse_move = False
    dragging_viewport.mouseMoveEvent(mouse_move(160, 150))

    after, _ = _camera(dragging_viewport)
    assert np.allclose(before, after, atol=1e-4)


def test_moving_without_a_drag_leaves_the_camera_alone(dragging_viewport):
    before, _ = _camera(dragging_viewport)

    dragging_viewport.mouseMoveEvent(mouse_move(300, 200, buttons=Qt.MouseButton.NoButton))

    after, _ = _camera(dragging_viewport)
    assert np.allclose(before, after)
    assert dragging_viewport._mouse_locked is False


# -- The infinite-range trick ------------------------------------------


def test_the_pointer_is_warped_back_after_each_move(dragging_viewport, fake_cursor):
    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    fake_cursor.clear()

    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))

    assert fake_cursor == [ANCHOR]


def test_the_virtual_position_accumulates_past_the_widget(dragging_viewport):
    """
    The point of the lock: a drag can keep going after the pointer would have
    left the 400px-wide widget. The virtual position is what VTK sees.
    """
    dragging_viewport.mousePressEvent(mouse_press(200, 150))

    for _ in range(3):
        dragging_viewport._ignore_next_mouse_move = False
        dragging_viewport.mouseMoveEvent(mouse_move(400, 150))

    assert dragging_viewport._mouse_virtual_local_pos.x() == 200 + 3 * 200
    assert dragging_viewport._mouse_virtual_local_pos.x() > dragging_viewport.width()


def test_the_warp_back_is_swallowed(dragging_viewport):
    """
    Warping the pointer generates a move event of its own. Acting on it would
    undo the drag, so the next move is dropped -- exactly once.
    """
    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))
    assert dragging_viewport._ignore_next_mouse_move is True

    dragging_viewport.mouseMoveEvent(mouse_move(200, 150))  # the warp's own event

    assert dragging_viewport._mouse_virtual_local_pos == QPoint(240, 150)
    assert dragging_viewport._ignore_next_mouse_move is False


def test_a_move_that_goes_nowhere_does_not_warp(dragging_viewport, fake_cursor):
    """A null delta must not cost a pointer warp or arm the skip flag."""
    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    fake_cursor.clear()

    dragging_viewport.mouseMoveEvent(mouse_move(200, 150))

    assert fake_cursor == []
    assert dragging_viewport._ignore_next_mouse_move is False


def test_a_fresh_lock_clears_a_pending_skip(dragging_viewport):
    """A drag that ends mid-warp must not eat the next drag's first move."""
    dragging_viewport.mousePressEvent(mouse_press(200, 150))
    dragging_viewport.mouseMoveEvent(mouse_move(240, 150))
    dragging_viewport.mouseReleaseEvent(mouse_release(240, 150))

    dragging_viewport.mousePressEvent(mouse_press(200, 150))

    assert dragging_viewport._ignore_next_mouse_move is False
