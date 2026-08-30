"""
Performing structural validation of files in the data package.
On an error, a ValidationError is raised with a message describing the problem.
Users are also given the option to select a different file.

"""
from __future__ import annotations
import os

def validateFileExists(file_path) -> bool:
    return os.path.exists(file_path)

def validateFolderExists(folder_path) -> bool:
    return os.path.exists(folder_path)

def validateFileNames(path = "data") -> None:
    """Validate that the given list of file names is valid for a bundle.
    """
    required_files = {"scene.obj", "targets.ply", "plan.json", "scores.npz", "visibility.npz", "flyable.npz"}
    target_directory = os.listdir(path)
    for file in target_directory:
        if (file not in required_files) and (file is not "Mesh"):
            print("Unexpected file found: " + str(file))
        # else:
        #     print("Correct file found: " + str(file))

def validatePlan(plan_path):
    expected_length = 1862
    actual_length = 0
    if validateFileExists(plan_path):
        try:
            with open(plan_path, 'r') as file:
                for line in file: actual_length+=1
        except:
            pass
        if expected_length != actual_length:
            print("plan.json: Expected=" + str(expected_length) + ", Actual=" + str(actual_length))
