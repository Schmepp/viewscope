"""Moving the active camera between the overview and planned viewpoints."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# viewscope_core as vc
import viewscope_core as vc

from . import transform


@dataclass(frozen=True)
class CameraInfo:
    """Where the viewer currently is, in terms the panels can display."""

    index: int
    count: int
    position: np.ndarray
    yaw: float
    pitch: float


class CameraController:
    """Owns the overview snapshot and the current viewpoint index."""

    def __init__(self, renderer, plan, diagonal: float, yfov_deg: float):
        self.renderer = renderer
        self.plan = plan
        self.diagonal = diagonal
        self.yfov_deg = yfov_deg

        self.index = None
        self._overview = None

    @property
    def count(self) -> int:
        return len(self.plan.positions)

    def save_overview(self):
        cam = self.renderer.GetActiveCamera()
        self._overview = (
            cam.GetPosition(),
            cam.GetFocalPoint(),
            cam.GetViewUp(),
            cam.GetViewAngle(),
        )

    def show_overview(self):
        """Return to the free-look camera. Returns None, matching `show`."""
        if self._overview is None:
            self.save_overview()
        else:
            cam = self.renderer.GetActiveCamera()
            position, focal, up, angle = self._overview
            cam.SetPosition(*position)
            cam.SetFocalPoint(*focal)
            cam.SetViewUp(*up)
            cam.SetViewAngle(angle)
            self.renderer.ResetCameraClippingRange()

        self.index = None
        return None

    def show(self, index: int):
        """Jump to a planned viewpoint. Index wraps at both ends."""
        if self.count == 0:
            return None

        # First jump away from free-look: remember where we were.
        if self.index is None:
            self.save_overview()

        self.index = index % self.count
        i = self.index

        pose = vc.camera_pose(
            self.plan.positions[i], self.plan.yaws_deg[i], self.plan.pitches_deg[i]
        )
        transform.apply_pose(
            self.renderer.GetActiveCamera(), pose, self.yfov_deg, self.diagonal
        )

        return CameraInfo(
            index=i,
            count=self.count,
            position=np.asarray(self.plan.positions[i], dtype=float),
            yaw=float(self.plan.yaws_deg[i]),
            pitch=float(self.plan.pitches_deg[i]),
        )

    def step(self, delta: int):
        """Move relative to the current viewpoint, starting from either end."""
        if self.index is None:
            return self.show(0 if delta > 0 else -1)
        return self.show(self.index + delta)
