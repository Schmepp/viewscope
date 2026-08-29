"""
Performing structural validation of files in the data package.
On an error, a ValidationError is raised with a message describing the problem.
Users are also given the option to select a different file.

"""

from __future__ import annotations

class FileValidate:
    pass

    def validateFileNames(self) -> None:
        """
        Validate that the given list of file names is valid for a bundle.
        """
        required_files = {"scene.obj", "targets.ply", "plan.json", "scores.npz", "visibility.npz", "flyable.npz"}