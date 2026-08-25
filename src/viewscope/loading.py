"""Reading a bundle off the interface thread."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from PySide6.QtCore import QThread, Signal

import viewscope_core as vc


@dataclass
class SceneData:
    """Everything one bundle contributes to the viewer.

    Plain trimesh / numpy objects only. VTK objects are built on the main
    thread, because the render window's GL context lives there.
    """

    mesh: trimesh.Geometry
    targets: np.ndarray
    normals: np.ndarray
    plan: vc.Plan
    scores: object | None = None
    scores_error: str | None = None

    @property
    def has_scores(self) -> bool:
        return self.scores is not None

    @property
    def camera_count(self) -> int:
        return len(self.plan.positions)

    @property
    def diagonal(self) -> float:
        bounds = self.mesh.bounds
        return float(np.linalg.norm(bounds[1] - bounds[0]))


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
