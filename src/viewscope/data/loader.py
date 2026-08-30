"""Reading a bundle off the interface thread."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

import viewscope_core as vc
from viewscope.data.scene import SceneData


class SceneLoader(QThread):
    """Parses a bundle directory and hands back a SceneData."""

    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)

    def run(self):
        try:
            self.loaded.emit(self._read())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _read(self) -> SceneData:
        self.progress.emit("Loading scene mesh...")
        mesh = vc.load_scene(str(self.data_dir / "scene.obj"))

        self.progress.emit("Loading targets...")
        targets, normals = vc.load_targets(str(self.data_dir / "targets.ply"))

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
