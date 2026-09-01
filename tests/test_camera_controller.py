"""
Moving the active camera between the overview and the planned viewpoints.

CameraController drives a vtkCamera on a bare renderer, so all of this runs
headless. It reads the plan out of SCENE_STORE rather than being handed one,
which is why every test here needs `loaded_store`.
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope.camera.controller import CameraController
from viewscope.camera.structs import CameraInfo
from viewscope.data.store import SCENE_STORE

YFOV = 53.1301


@pytest.fixture
def controller(renderer, loaded_store):
    renderer.ResetCamera()
    control = CameraController(renderer, YFOV)
    control.save_overview()
    return control


def _position(controller):
    return np.array(controller.renderer.GetActiveCamera().GetPosition())


# -- Counting ----------------------------------------------------------


def test_count_follows_the_plan(controller, loaded_store):
    assert controller.count == 2

    loaded_store.add_camera((1.0, 1.0, 1.0), yaw=0.0, pitch=0.0)

    assert controller.count == 3


def test_count_is_zero_without_a_scene(renderer):
    assert CameraController(renderer, YFOV).count == 0


# -- Jumping to a viewpoint --------------------------------------------


def test_show_moves_to_the_planned_position(controller, sample_plan):
    info = controller.show(0)

    assert isinstance(info, CameraInfo)
    assert np.allclose(_position(controller), sample_plan.positions[0])


def test_show_reports_the_viewpoint(controller, sample_plan):
    info = controller.show(1)

    assert info.index == 1
    assert np.allclose(info.position, sample_plan.positions[1])
    assert info.yaw == pytest.approx(sample_plan.yaws_deg[1])
    assert info.pitch == pytest.approx(sample_plan.pitches_deg[1])


def test_show_records_where_it_is(controller):
    controller.show(1)

    assert controller.index == 1


def test_show_wraps_past_the_end(controller):
    """The panel steps with N and P; running off either end should wrap."""
    assert controller.show(2).index == 0
    assert controller.show(3).index == 1


def test_show_wraps_before_the_start(controller):
    assert controller.show(-1).index == 1


def test_show_returns_nothing_without_cameras(renderer, scene_data, sample_plan):
    """An empty plan has nowhere to jump to."""
    scene_data.plan = type(sample_plan)(
        camera=sample_plan.camera,
        ids=(),
        positions=np.empty((0, 3)),
        yaws_deg=np.empty(0),
        pitches_deg=np.empty(0),
    )
    SCENE_STORE.set_scene(scene_data)

    assert CameraController(renderer, YFOV).show(0) is None


def test_show_returns_nothing_without_a_scene(renderer):
    assert CameraController(renderer, YFOV).show(0) is None


# -- The overview ------------------------------------------------------


def test_overview_returns_the_camera_to_where_it_was(controller):
    before = _position(controller)
    controller.show(0)

    controller.show_overview()

    assert np.allclose(_position(controller), before)
    assert controller.index is None


def test_overview_snapshots_on_the_first_jump_away(controller):
    """
    A free-look camera the user has dragged is not the saved overview, so the
    first jump to a viewpoint has to re-snapshot it.
    """
    controller.renderer.GetActiveCamera().SetPosition(9.0, 9.0, 9.0)
    controller.index = None
    controller._overview = None

    controller.show(0)
    controller.show_overview()

    assert np.allclose(_position(controller), [9.0, 9.0, 9.0])


def test_overview_without_a_snapshot_takes_one(controller):
    controller._overview = None

    controller.show_overview()

    assert controller._overview is not None
    assert controller.index is None


def test_overview_restores_the_view_angle(controller):
    controller.renderer.GetActiveCamera().SetViewAngle(30.0)
    controller.save_overview()
    controller.show(0)

    controller.show_overview()

    assert controller.renderer.GetActiveCamera().GetViewAngle() == pytest.approx(30.0)


# -- Stepping ----------------------------------------------------------


def test_step_forward_from_the_overview_starts_at_the_first(controller):
    assert controller.step(1).index == 0


def test_step_back_from_the_overview_starts_at_the_last(controller):
    assert controller.step(-1).index == 1


def test_step_moves_relative_to_the_current_viewpoint(controller):
    controller.show(0)

    assert controller.step(1).index == 1


def test_step_wraps_round(controller):
    controller.show(1)

    assert controller.step(1).index == 0
    assert controller.step(-1).index == 1


def test_stepping_after_the_overview_starts_over(controller):
    controller.show(1)
    controller.show_overview()

    assert controller.step(1).index == 0
