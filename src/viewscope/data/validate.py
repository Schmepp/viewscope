"""
Performing structural validation of files in the data package.
Checking the existence of files, filenames, and whether enough viewpoints are in the plan file.

The methods here either return just a boolean, or a tuple (boolean + error message).

This doesn't spawn any Dialogs nor raise Errors.
SceneLoader emits the signal to MainWindow, which spawns the FileErrorDialog
"""

from __future__ import annotations

import json
import os


def validate_file_exists(file_path) -> bool:
    return os.path.exists(file_path)


def validate_folder_exists(folder_path) -> bool:
    return os.path.exists(folder_path)


def validate_required_files(path="data"):
    """Validate that the required files are found within a folder.
    If not found, return the status(False) and the error message"""
    required_files = {
        "scene.obj",
        "targets.ply",
        "plan.json",
        "scores.npz",
        "visibility.npz",
        "flyable.npz",
    }
    target_directory = set(os.listdir(path))

    missing_files = required_files - target_directory  # the set of missing files

    if missing_files:
        error_message = f"Error: Missing these required files: [ {', '.join(missing_files)} ]."
        return False, error_message
    return True, "Sucess"


def validate_plan(plan_path, expected_viewpoints=None):
    """Compare the expected viewpoints to the actual viewpoints counted within the file.
    Return's a tuple: the success(True/False) and an status message (Sucess/Error)

    expected_viewpoints is the count a shipped bundle is known to hold, such as
    185 for data/kiri. Projects the user adds bring their own plan, so passing
    None asks only for a plan that exists and holds at least one viewpoint."""
    if not validate_file_exists(plan_path):
        return False, f"Error: {plan_path} does not exist."

    actual_viewpoints = count_view_points(plan_path)

    if expected_viewpoints is None:
        if actual_viewpoints < 1:
            return False, "Error: plan.json holds no viewpoints."
        return True, "Success"

    if actual_viewpoints == expected_viewpoints:
        return True, "Success"

    error_message = (
        f"Error: plan.json was expecting {expected_viewpoints}"
        + f" viewpoints but received {actual_viewpoints} viewpoints."
    )
    return False, error_message


def count_view_points(plan_path) -> int:
    with open(plan_path) as f:  # Open and read file
        data = json.load(f)

    viewpoints = data.get("viewpoints", [])  # Retrieve values and store in a list
    total_points = len(viewpoints)

    return total_points
