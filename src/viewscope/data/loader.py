"""Reading a bundle off the interface thread."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

import viewscope_core as vc
from viewscope.data.scene import SceneData

from .validate import (
    validate_plan,
    validate_required_files,
)


class SceneLoader(QThread):
    """Parses a bundle directory and hands back a SceneData."""

    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    plan_validation_failed = Signal(str, str, str)  # Title + Error + Action message
    filename_validation_failed = Signal(str, str, str)  # Title + Error + Action message

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.error_message = None

    def run(self):
        try:
            self.loaded.emit(self._read())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _read(self) -> SceneData:

        # -- Perform validation of Data folder
        filenames_validated, self.error_message = validate_required_files(
            str(self.data_dir)
        )  # Validate filenames first
        if not filenames_validated:
            self.call_error_dialog(
                "Unexpected Files found",
                self.error_message,
                """Tip: Open the Data folder and move or delete files that are not one of these:
                \tscene.obj, targets.ply, plan.json, scores.npz, visibility.npz, flyable.npz.
                \nClose the application, and re-launch afterwards.
                """,
            )

        plan_validated, self.error_message = validate_plan(  # Validate plan.json next
            str(self.data_dir / "plan.json")
        )
        if not plan_validated:
            self.call_error_dialog(
                "Validation Error: missing viewpoints",
                self.error_message,
                """Tip: Open the Data folder and replace your files.
                "\nClose the application, and re-launch afterwards.""",
            )

        self.progress.emit("Loading scene mesh...")
        try:
            mesh = vc.load_scene(str(self.data_dir / "scene.obj"))
        except Exception:
            self.call_error_dialog(
                "Invalid file",
                "Expected: scene.obj, but receieved an invalid file instead.",
                "Locate a copy of scene.obj and place it inside the data folder.",
            )

        self.progress.emit("Loading targets...")
        try:
            targets, normals = vc.load_targets(str(self.data_dir / "targets.ply"))
        except Exception:
            self.call_error_dialog(
                "Invalid file",
                "Expected: target.ply, but received an invalid file instead.",
                "Locate a copy of targets.ply and place it inside the data folder.",
            )

        self.progress.emit("Loading plan...")
        plan = vc.load_plan(str(self.data_dir / "plan.json"))

        self.progress.emit("Loading scores...")
        scores, scores_error = None, None
        try:
            scores = vc.load_scores(
                str(self.data_dir / "scores.npz"), len(targets), len(plan.positions)
            )
        except Exception as exc:
            # Scores are optional: the viewer still shows geometry without them.
            scores_error = str(exc)

        self.progress.emit("Loading visibility...")
        visibility = self._read_visibility(len(targets))

        return SceneData(mesh, targets, normals, plan, scores, scores_error, visibility)

    def _read_visibility(self, target_count: int):
        """The shipped camera-by-target visibility matrix, or None.

        Optional, like the scores: without it the viewer recomputes visibility
        through the library on demand.
        """
        path = self.data_dir / "visibility.npz"
        if not path.exists():
            return None

        try:
            with np.load(path, allow_pickle=False) as bundle:
                visible = bundle["visible"]
            if visible.dtype != np.bool_ or visible.ndim != 2 or visible.shape[1] != target_count:
                raise ValueError("expected a boolean matrix of cameras by targets")
        except Exception as exc:
            print(f"visibility unavailable: {exc}")
            return None

        return visible

    def call_error_dialog(self, error_title, error_message, action_message):
        """Emit a file_validation_error signal to viewport.py.
        This contains: error title, error message, and an action message."""
        self.filename_validation_failed.emit(error_title, error_message, action_message)
