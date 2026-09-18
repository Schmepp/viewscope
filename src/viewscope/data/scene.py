"""Data structures representing loaded scene data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

import viewscope_core as vc


@dataclass
class SceneData:
    """
    Everything one bundle contributes to the viewer.

    Plain trimesh / numpy objects only. VTK objects are built on the main
    thread, because the render window's GL context lives there.
    """

    mesh: trimesh.Geometry
    targets: np.ndarray
    normals: np.ndarray
    plan: vc.Plan
    scores: vc.Scores | None = None
    scores_error: str | None = None
    visibility: np.ndarray | None = None

    # NOTE(Adam): This is where the bundle was read from.
    #             The camera view needs it to find the full-resolution model
    #             that sits beside the simplified one.
    data_dir: Path | None = None

    @property
    def has_scores(self) -> bool:
        return self.scores is not None

    @property
    def diagonal(self) -> float:
        bounds = self.mesh.bounds
        return float(np.linalg.norm(bounds[1] - bounds[0]))

    @property
    def centre(self) -> np.ndarray:
        """Where the model sits, as the middle of its bounding box.

        Not every bundle is built about the world origin - a model cut out of
        a larger survey keeps that survey's coordinates - so anything asking
        where a camera stands relative to the model has to ask from here.
        This is the same centre `build_bundle` plans the viewpoints around.
        """
        return np.asarray(self.mesh.bounds, dtype=float).mean(axis=0)
