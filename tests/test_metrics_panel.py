"""
The read-only figures panel.

MetricsPanel holds no state of its own: it reads SCENE_STORE and formats what
it is handed. Every assertion here is on the text a user would actually read.
"""

from __future__ import annotations

import numpy as np

from viewscope.camera.structs import CameraInfo
from viewscope.MetricsPanel import MetricsPanel
from viewscope.scene import FieldStats

BUNDLE_KEYS = ["Vertices", "Triangles", "Diagonal", "Targets", "Cameras"]
FIELD_KEYS = ["Field", "Min", "Mean", "Max"]
VIEWPOINT_KEYS = ["Camera", "Position", "Yaw", "Pitch"]


def _text(panel, key):
    return panel.rows[key].text()


# -- Construction ------------------------------------------------------


def test_every_row_exists_and_starts_blank(qapp):
    panel = MetricsPanel()

    assert set(panel.rows) == set(BUNDLE_KEYS + FIELD_KEYS + VIEWPOINT_KEYS)
    assert all(_text(panel, key) == "--" for key in panel.rows)


def test_setting_an_unknown_key_is_ignored(qapp):
    """The panel is fed by several callers; a typo must not crash the app."""
    panel = MetricsPanel()

    panel.set("Nonexistent", 42)

    assert "Nonexistent" not in panel.rows


def test_clear_blanks_the_named_rows(qapp):
    panel = MetricsPanel()
    panel.set("Yaw", "12.00")

    panel.clear(["Yaw"])

    assert _text(panel, "Yaw") == "--"


# -- Bundle figures ----------------------------------------------------


def test_bundle_figures_come_from_the_scene(qapp, loaded_store, sample_mesh):
    panel = MetricsPanel()

    panel.show_bundle()

    assert _text(panel, "Vertices") == f"{len(sample_mesh.vertices):,}"
    assert _text(panel, "Triangles") == f"{len(sample_mesh.faces):,}"
    assert _text(panel, "Targets") == "3"
    assert _text(panel, "Cameras") == "2"


def test_the_diagonal_is_shown_to_two_places(qapp, loaded_store):
    panel = MetricsPanel()

    panel.show_bundle()

    # A 2x2x2 box: sqrt(12) ~= 3.46
    assert _text(panel, "Diagonal") == "3.46"


def test_large_counts_are_grouped(qapp, loaded_store, scene_data):
    """A raw 1234567 is unreadable at a glance."""
    scene_data.targets = np.zeros((1234567, 3))
    panel = MetricsPanel()

    panel.show_bundle()

    assert _text(panel, "Targets") == "1,234,567"


def test_bundle_figures_are_zero_without_a_scene(qapp):
    panel = MetricsPanel()

    panel.show_bundle()

    assert _text(panel, "Vertices") == "0"
    assert _text(panel, "Cameras") == "0"
    assert _text(panel, "Diagonal") == "0.00"


def test_the_camera_count_follows_a_spawned_camera(qapp, loaded_store):
    """The panel subscribes to plan_changed, so no caller has to refresh it."""
    panel = MetricsPanel()
    panel.show_bundle()

    loaded_store.add_camera((1.0, 1.0, 1.0), yaw=0.0, pitch=0.0)

    assert _text(panel, "Cameras") == "3"


# -- Scalar field ------------------------------------------------------


def test_field_stats_are_shown_to_four_places(qapp):
    panel = MetricsPanel()

    panel.show_field(FieldStats("score_8", 0.0, 0.5, 1.0))

    assert _text(panel, "Field") == "score_8"
    assert _text(panel, "Min") == "0.0000"
    assert _text(panel, "Mean") == "0.5000"
    assert _text(panel, "Max") == "1.0000"


def test_a_bundle_without_scores_says_so(qapp):
    panel = MetricsPanel()
    panel.show_field(FieldStats("score_8", 0.0, 0.5, 1.0))

    panel.show_field(None)

    assert _text(panel, "Field") == "unavailable"
    assert all(_text(panel, key) == "--" for key in ["Min", "Mean", "Max"])


# -- Viewpoint ---------------------------------------------------------


def test_the_viewpoint_is_numbered_for_humans(qapp, loaded_store):
    """Index 0 of 2 reads as camera 1 of 2."""
    panel = MetricsPanel()

    panel.show_camera(
        CameraInfo(index=0, position=np.array([1.0, 2.0, 3.0]), yaw=45.0, pitch=-10.0)
    )

    assert _text(panel, "Camera") == "1 of 2"
    assert _text(panel, "Position") == "1.00, 2.00, 3.00"
    assert _text(panel, "Yaw") == "45.00"
    assert _text(panel, "Pitch") == "-10.00"


def test_the_overview_blanks_the_viewpoint(qapp, loaded_store):
    panel = MetricsPanel()
    panel.show_camera(CameraInfo(index=0, position=np.zeros(3), yaw=0.0, pitch=0.0))

    panel.show_camera(None)

    assert all(_text(panel, key) == "--" for key in VIEWPOINT_KEYS)
