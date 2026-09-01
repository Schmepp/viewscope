"""
Structural validation of the data bundle.

These are the checks that fire before anything is parsed, and they decide
whether the user sees a scene or an error dialog.
"""

from __future__ import annotations

import json

import pytest

from viewscope.data.validate import (
    count_view_points,
    validate_file_exists,
    validate_folder_exists,
    validate_plan,
    validate_required_files,
)

REQUIRED = [
    "scene.obj",
    "targets.ply",
    "plan.json",
    "scores.npz",
    "visibility.npz",
    "flyable.npz",
]
EXPECTED_VIEWPOINTS = 185


def _write_plan(path, count):
    path.write_text(json.dumps({"viewpoints": [{"id": f"vp{i}"} for i in range(count)]}))
    return path


@pytest.fixture
def bundle(tmp_path):
    """A directory holding every required filename, all empty."""
    for name in REQUIRED:
        (tmp_path / name).touch()
    return tmp_path


# -- Existence ---------------------------------------------------------


def test_a_present_file_validates(tmp_path):
    path = tmp_path / "plan.json"
    path.touch()

    assert validate_file_exists(path) is True


def test_a_missing_file_does_not(tmp_path):
    assert validate_file_exists(tmp_path / "nope.json") is False


def test_a_present_folder_validates(tmp_path):
    assert validate_folder_exists(tmp_path) is True


def test_a_missing_folder_does_not(tmp_path):
    assert validate_folder_exists(tmp_path / "nope") is False


# -- Required files ----------------------------------------------------


def test_a_complete_bundle_passes(bundle):
    ok, message = validate_required_files(str(bundle))

    assert ok is True
    assert message == "Sucess"


def test_a_missing_file_is_named_in_the_message(bundle):
    (bundle / "scores.npz").unlink()

    ok, message = validate_required_files(str(bundle))

    assert ok is False
    assert "scores.npz" in message


def test_every_missing_file_is_listed(bundle):
    (bundle / "scores.npz").unlink()
    (bundle / "flyable.npz").unlink()

    _, message = validate_required_files(str(bundle))

    assert "scores.npz" in message
    assert "flyable.npz" in message


def test_extra_files_are_allowed(bundle):
    """The check is for missing files, not for a tidy directory."""
    (bundle / "notes.txt").touch()

    ok, _ = validate_required_files(str(bundle))

    assert ok is True


def test_an_empty_directory_fails(tmp_path):
    ok, message = validate_required_files(str(tmp_path))

    assert ok is False
    for name in REQUIRED:
        assert name in message


# -- The plan ----------------------------------------------------------


def test_counting_viewpoints(tmp_path):
    path = _write_plan(tmp_path / "plan.json", 3)

    assert count_view_points(path) == 3


def test_counting_an_empty_plan(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"viewpoints": []}))

    assert count_view_points(path) == 0


def test_counting_a_plan_with_no_viewpoints_key(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({}))

    assert count_view_points(path) == 0


def test_a_plan_with_the_expected_count_passes(tmp_path):
    path = _write_plan(tmp_path / "plan.json", EXPECTED_VIEWPOINTS)

    ok, message = validate_plan(str(path))

    assert ok is True
    assert message == "Success"


def test_a_short_plan_reports_both_counts(tmp_path):
    path = _write_plan(tmp_path / "plan.json", 10)

    ok, message = validate_plan(str(path))

    assert ok is False
    assert str(EXPECTED_VIEWPOINTS) in message
    assert "10" in message


def test_validate_plan_returns_nothing_when_the_file_is_missing(tmp_path):
    """
    A gap worth knowing about: the function falls off the end and returns None
    rather than a (bool, message) pair. SceneLoader unpacks the result, so a
    missing plan.json raises TypeError instead of showing the error dialog.
    """
    assert validate_plan(str(tmp_path / "nope.json")) is None


def test_a_missing_plan_breaks_the_loader_contract(tmp_path):
    """The consequence of the gap above, pinned so a fix is noticed here too."""
    with pytest.raises(TypeError):
        _ok, _message = validate_plan(str(tmp_path / "nope.json"))
