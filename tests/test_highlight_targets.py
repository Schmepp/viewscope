"""
Which targets a viewpoint can see.

Shipped viewpoints come out of the bundle's visibility matrix. Cameras the
user has spawned are not in that matrix, so they are recomputed through the
library off an offscreen renderer -- which needs a GL context of its own, and
is stubbed here rather than built.
"""

from __future__ import annotations

import numpy as np
import pytest

from viewscope import highlight_targets as highlight_module
from viewscope.highlight_targets import TargetVisibility


@pytest.fixture
def stub_renderer(monkeypatch):
    """
    Replace vc.SceneRenderer and vc.camera_visibility.

    Returns the list of poses the depth renderer was asked to render, so a
    test can tell a cache hit from a recompute.
    """

    class Rendered(list):
        """A list of poses, with the stub instances hung off it."""

        built: list = []

    rendered = Rendered()
    rendered.built = []

    class StubSceneRenderer:
        def __init__(self, mesh, width, height, yfov_deg):
            rendered.built.append(self)
            self.closed = False

        def render_depth(self, pose):
            rendered.append(pose)
            return np.zeros((4, 4))

        def close(self):
            self.closed = True

    monkeypatch.setattr(highlight_module.vc, "SceneRenderer", StubSceneRenderer)
    monkeypatch.setattr(
        highlight_module.vc,
        "camera_visibility",
        lambda *args: np.array([False, True, False]),
    )
    return rendered


# -- Shipped masks -----------------------------------------------------


def test_a_shipped_camera_uses_the_bundle_matrix(scored_scene_data):
    visibility = TargetVisibility(scored_scene_data)

    assert _mask(visibility, 0).tolist() == [True, False, True]
    assert _mask(visibility, 1).tolist() == [False, True, False]


def test_the_mask_is_boolean(scored_scene_data):
    """The cloud maps it through a two-entry lookup table, so 0/1 matter."""
    mask = _mask(TargetVisibility(scored_scene_data), 0)

    assert mask.dtype == np.bool_


def test_the_overview_has_no_mask(scored_scene_data):
    assert TargetVisibility(scored_scene_data).mask_for(None) is None


@pytest.mark.parametrize("index", [-1, 2, 99])
def test_an_index_outside_the_plan_has_no_mask(scored_scene_data, index):
    assert TargetVisibility(scored_scene_data).mask_for(index) is None


# -- Recomputed masks --------------------------------------------------


def test_a_spawned_camera_is_recomputed(scored_scene_data, stub_renderer):
    """
    The bundle ships two rows; a third camera has to go through the library.
    """
    scored_scene_data.plan = _with_extra_camera(scored_scene_data.plan)
    visibility = TargetVisibility(scored_scene_data)

    assert _mask(visibility, 2).tolist() == [False, True, False]
    assert len(stub_renderer) == 1


def test_a_bundle_with_no_matrix_recomputes_everything(scene_data, stub_renderer):
    scene_data.visibility = None
    visibility = TargetVisibility(scene_data)

    visibility.mask_for(0)

    assert len(stub_renderer) == 1


def test_the_depth_renderer_is_built_once(scored_scene_data, stub_renderer):
    """Building one is expensive; two cameras must share it."""
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)

    visibility.mask_for(0)
    visibility.mask_for(1)

    assert len(stub_renderer.built) == 1


# -- Caching -----------------------------------------------------------


def test_a_mask_is_computed_only_once(scored_scene_data, stub_renderer):
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)

    visibility.mask_for(0)
    visibility.mask_for(0)

    assert len(stub_renderer) == 1


def test_forget_drops_one_mask(scored_scene_data, stub_renderer):
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)
    visibility.mask_for(0)
    visibility.mask_for(1)

    visibility.forget(0)

    assert set(visibility._cache) == {1}


def test_forget_drops_everything_by_default(scored_scene_data):
    visibility = TargetVisibility(scored_scene_data)
    visibility.mask_for(0)
    visibility.mask_for(1)

    visibility.forget()

    assert visibility._cache == {}


def test_forgetting_an_uncached_camera_is_harmless(scored_scene_data):
    visibility = TargetVisibility(scored_scene_data)

    visibility.forget(0)

    assert visibility._cache == {}


def test_forgetting_forces_a_recompute(scored_scene_data, stub_renderer):
    """A camera that has moved must not keep its stale mask."""
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)
    visibility.mask_for(0)

    visibility.forget(0)
    visibility.mask_for(0)

    assert len(stub_renderer) == 2


# -- Shutdown ----------------------------------------------------------


def test_close_releases_the_gl_context(scored_scene_data, stub_renderer):
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)
    visibility.mask_for(0)

    visibility.close()

    assert stub_renderer.built[0].closed is True
    assert visibility._renderer is None


def test_close_without_a_renderer_is_harmless(scored_scene_data):
    """MainWindow.closeEvent calls this whether or not one was ever built."""
    TargetVisibility(scored_scene_data).close()


def test_close_is_idempotent(scored_scene_data, stub_renderer):
    scored_scene_data.visibility = None
    visibility = TargetVisibility(scored_scene_data)
    visibility.mask_for(0)

    visibility.close()
    visibility.close()

    assert visibility._renderer is None


def _with_extra_camera(plan):
    return type(plan)(
        camera={"width": 64, "height": 48, "yfov_deg": 53.1301},
        ids=(*plan.ids, "vp3"),
        positions=np.vstack([plan.positions, [[1.0, 1.0, 1.0]]]),
        yaws_deg=np.append(plan.yaws_deg, 0.0),
        pitches_deg=np.append(plan.pitches_deg, 0.0),
    )


def _mask(visibility, index):
    """mask_for, asserting a mask actually came back."""
    mask = visibility.mask_for(index)
    assert mask is not None
    return mask
