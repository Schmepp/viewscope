"""
Reading a bundle off the interface thread.

SceneLoader is a QThread, but `run` and `_read` are ordinary methods -- calling
them directly keeps the tests deterministic instead of waiting on a thread.
The viewscope_core readers are stubbed, so no real .obj or .ply is parsed.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from viewscope.data import loader as loader_module
from viewscope.data.loader import SceneLoader
from viewscope.data.scene import SceneData

REQUIRED = [
    "scene.obj",
    "targets.ply",
    "plan.json",
    "scores.npz",
    "visibility.npz",
    "flyable.npz",
]


@pytest.fixture
def bundle_dir(tmp_path, sample_plan):
    """A directory that passes both validation checks."""
    for name in REQUIRED:
        (tmp_path / name).touch()

    (tmp_path / "plan.json").write_text(
        json.dumps({"viewpoints": [{"id": f"vp{i}"} for i in range(185)]})
    )
    return tmp_path


@pytest.fixture
def stub_readers(monkeypatch, sample_mesh, sample_plan, sample_scores):
    """Stand in for the viewscope_core file readers."""
    monkeypatch.setattr(loader_module.vc, "load_scene", lambda path: sample_mesh)
    monkeypatch.setattr(
        loader_module.vc,
        "load_targets",
        lambda path: (np.zeros((3, 3)), np.zeros((3, 3))),
    )
    monkeypatch.setattr(loader_module.vc, "load_plan", lambda path: sample_plan)
    monkeypatch.setattr(
        loader_module.vc,
        "load_scores",
        lambda path, n_targets, n_cameras: sample_scores,
    )


def _write_visibility(path, array):
    np.savez(path, visible=array)


# -- The happy path ----------------------------------------------------


def test_a_good_bundle_loads(qapp, bundle_dir, stub_readers, sample_mesh):
    scene = SceneLoader(bundle_dir)._read()

    assert isinstance(scene, SceneData)
    assert scene.mesh is sample_mesh
    assert scene.has_scores is True
    assert scene.scores_error is None


def test_loading_reports_progress(qapp, bundle_dir, stub_readers, spy):
    """The status bar is the only feedback during a slow load."""
    loader = SceneLoader(bundle_dir)
    watcher = spy(loader.progress)

    loader._read()

    assert [call[0] for call in watcher.calls] == [
        "Loading scene mesh...",
        "Loading targets...",
        "Loading plan...",
        "Loading scores...",
        "Loading visibility...",
    ]


def test_run_emits_the_scene(qapp, bundle_dir, stub_readers, spy):
    loader = SceneLoader(bundle_dir)
    watcher = spy(loader.loaded)

    loader.run()

    assert watcher.count == 1
    assert isinstance(watcher.last, SceneData)


def test_run_reports_a_failure_instead_of_raising(qapp, tmp_path, spy):
    """A thread that raises takes the exception with it; the UI must hear."""
    loader = SceneLoader(tmp_path / "missing")
    failures = spy(loader.failed)

    loader.run()

    assert failures.count == 1
    assert "Error" in failures.last or "error" in failures.last


# -- Validation --------------------------------------------------------


def test_a_missing_file_raises_the_error_dialog(qapp, bundle_dir, stub_readers, spy):
    (bundle_dir / "flyable.npz").unlink()
    loader = SceneLoader(bundle_dir)
    watcher = spy(loader.filename_validation_failed)

    loader._read()

    assert watcher.count == 1
    title, message, action = watcher.calls[0]
    assert title == "Unexpected Files found"
    assert "flyable.npz" in message
    assert "data folder" in action.lower()


def test_a_short_plan_raises_the_error_dialog(qapp, bundle_dir, stub_readers, spy):
    (bundle_dir / "plan.json").write_text(json.dumps({"viewpoints": [{"id": "vp1"}]}))
    loader = SceneLoader(bundle_dir)
    watcher = spy(loader.filename_validation_failed)

    loader._read()

    titles = [call[0] for call in watcher.calls]
    assert "Validation Error: missing viewpoints" in titles


def test_validation_does_not_stop_the_load(qapp, bundle_dir, stub_readers):
    """
    Worth knowing: the loader reports the problem and carries on parsing. The
    dialog is what actually blocks the user, not a return from _read.
    """
    (bundle_dir / "flyable.npz").unlink()

    scene = SceneLoader(bundle_dir)._read()

    assert isinstance(scene, SceneData)


# -- Optional pieces ---------------------------------------------------


def test_missing_scores_are_not_fatal(qapp, bundle_dir, stub_readers, monkeypatch):
    """The viewer still shows geometry without them."""

    def explode(path, n_targets, n_cameras):
        raise FileNotFoundError("scores.npz is empty")

    monkeypatch.setattr(loader_module.vc, "load_scores", explode)

    scene = SceneLoader(bundle_dir)._read()

    assert scene.has_scores is False
    assert scene.scores_error is not None
    assert "scores.npz is empty" in scene.scores_error


def test_a_shipped_visibility_matrix_is_read(qapp, bundle_dir, stub_readers):
    matrix = np.array([[True, False, True], [False, True, False]])
    _write_visibility(bundle_dir / "visibility.npz", matrix)

    scene = SceneLoader(bundle_dir)._read()

    assert scene.visibility is not None
    assert scene.visibility.tolist() == matrix.tolist()


def test_a_missing_visibility_file_is_not_fatal(qapp, bundle_dir, stub_readers):
    (bundle_dir / "visibility.npz").unlink()
    loader = SceneLoader(bundle_dir)

    assert loader._read_visibility(3) is None


def test_a_visibility_matrix_of_the_wrong_width_is_rejected(qapp, bundle_dir, stub_readers):
    """One column per target, or the mask would misalign with the cloud."""
    _write_visibility(bundle_dir / "visibility.npz", np.zeros((2, 99), dtype=bool))

    assert SceneLoader(bundle_dir)._read_visibility(3) is None


def test_a_non_boolean_visibility_matrix_is_rejected(qapp, bundle_dir, stub_readers):
    _write_visibility(bundle_dir / "visibility.npz", np.zeros((2, 3), dtype=np.float32))

    assert SceneLoader(bundle_dir)._read_visibility(3) is None


def test_a_one_dimensional_visibility_matrix_is_rejected(qapp, bundle_dir, stub_readers):
    _write_visibility(bundle_dir / "visibility.npz", np.zeros(3, dtype=bool))

    assert SceneLoader(bundle_dir)._read_visibility(3) is None


def test_an_unreadable_visibility_file_is_rejected(qapp, bundle_dir, stub_readers):
    (bundle_dir / "visibility.npz").write_bytes(b"not an npz")

    assert SceneLoader(bundle_dir)._read_visibility(3) is None


# -- Construction ------------------------------------------------------


def test_the_data_directory_is_coerced_to_a_path(qapp, tmp_path):
    """MainWindow passes a Path, but config and tests hand over strings."""
    as_string: Any = str(tmp_path)

    loader = SceneLoader(as_string)

    assert loader.data_dir == tmp_path
