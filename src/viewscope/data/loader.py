"""Reading a bundle off the interface thread."""

from __future__ import annotations

from pathlib import Path

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

        return SceneData(mesh, targets, normals, plan, scores, scores_error)
