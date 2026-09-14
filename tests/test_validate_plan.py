# Unit tests for the viewpoint count check in src/viewscope/data/validate.py

import json

from viewscope.data.validate import validate_plan


def write_plan(folder, viewpoints):
    path = folder / "plan.json"
    path.write_text(json.dumps({"viewpoints": [{"id": f"vp{i:03d}"} for i in range(viewpoints)]}))
    return path


def test_a_shipped_bundle_must_hold_the_count_it_shipped_with(tmp_path):
    path = write_plan(tmp_path, 185)

    assert validate_plan(str(path), 185) == (True, "Success")

    ok, message = validate_plan(str(path), 120)
    assert ok is False
    assert "185" in message


def test_any_non_empty_plan_passes_when_no_count_is_expected(tmp_path):
    """Projects the user adds bring their own plan, of a size we cannot know."""
    ok, _ = validate_plan(str(write_plan(tmp_path, 120)))
    assert ok is True

    ok, message = validate_plan(str(write_plan(tmp_path, 0)))
    assert ok is False
    assert "no viewpoints" in message


def test_a_missing_plan_reports_instead_of_raising(tmp_path):
    ok, message = validate_plan(str(tmp_path / "plan.json"))

    assert ok is False
    assert "does not exist" in message
