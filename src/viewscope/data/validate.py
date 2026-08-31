"""
Performing structural validation of files in the data package.
On an error, a ValidationError is raised with a message describing the problem.
Users are also given the option to select a different file.

"""
from __future__ import annotations
import os
import json

def validate_file_exists(file_path) -> bool:
    return os.path.exists(file_path)

def validate_folder_exists(folder_path) -> bool:
    return os.path.exists(folder_path)

def validate_filenames(path = "data") -> None:
    """Validate that the given list of file names is valid for a bundle.
    """
    required_files = {"scene.obj", "targets.ply", "plan.json", "scores.npz", "visibility.npz", "flyable.npz"}
    target_directory = os.listdir(path)
    for file in target_directory:
        if (file not in required_files) and (file != "Mesh"):
            print("Unexpected file found: " + str(file))

def validate_plan(plan_path):
    expected_viewpoints = 185
    if validate_file_exists(plan_path):
        actual_viewpoints = count_view_points(plan_path)
        if actual_viewpoints == expected_viewpoints:
            print(f"Sucess! All {expected_viewpoints} have been loaded.")
        else:
            print(f"Error: plan.json was expecting {expected_viewpoints} but received {actual_viewpoints} viewpoints.")

def count_view_points(plan_path) -> int:
    with open(plan_path, 'r') as f: # Open and read file
        data = json.load(f)

    viewpoints = data.get('viewpoints', []) # Retrieve values and store in a list
    total_points = len(viewpoints)

    return total_points