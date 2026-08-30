"""Data structures representing loaded scene data."""

from __future__ import annotations

from dataclasses import dataclass

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
    scores: object | None = None
    scores_error: str | None = None
    visibility: np.ndarray | None = None

    @property
    def has_scores(self) -> bool:
        return self.scores is not None

    @property
    def diagonal(self) -> float:
        bounds = self.mesh.bounds
        return float(np.linalg.norm(bounds[1] - bounds[0]))
