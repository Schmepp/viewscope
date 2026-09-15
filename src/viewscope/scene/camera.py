from __future__ import annotations

from enum import Enum
import math
from dataclasses import dataclass, replace

import numpy as np

import vtk

class CameraMode(Enum):
    LOOK_AT = 0,
    TRACKBALL = 1


@dataclass(frozen=True)
class CameraOrbitState:
    """
    Explicit free-look camera state: pivot + distance + yaw/pitch.

    Deliberately not derived from scene bounds after construction, so
    nothing in the renderer can perturb it as a side effect.
    """
    pivot: tuple[float, float, float]
    distance: float
    yaw: float  # Radians
    pitch: float # Radians
    view_angle: float # Degrees

    def camera_position(self) -> tuple[float, ...]:
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        offset = (self.distance * cp * sy, -self.distance * cp * cy, self.distance * sp)

        return tuple(p + o for p, o in zip(self.pivot, offset))


class SceneCameraController:
    """Perspective look-at scene camera."""
    YAW_SENSITIVITY: float = 0.005 # rad/px
    PITCH_SENSITIVITY: float = 0.005    # rad/px
    PAN_SENSITIVITY: float = 0.0015  # fraction of distance/px
    ZOOM_SENSITIVITY: float = 0.0025  # fraction of distance/unit
    PITCH_LIMIT: float = math.radians(89.0)
    MIN_DISTANCE: float = 1e-3

    def __init__(self, renderer: vtk.vtkRenderer, yfov_deg: float):
        self.renderer = renderer
        self.yfov_deg = yfov_deg
        self._orbit: CameraOrbitState | None = None

    # -- Orbit state -----------------------------------------------------

    def _orbit_from_camera(self) -> CameraOrbitState:
        """
        Derive pivot/distance/yaw/pitch from wherever the camera currently is.

        Used to capture state after a deliberate reframe (ResetCamera) and
        to adopt whatever pose we're in when manipulation resumes from a
        planned viewpoint.
        """
        cam = self.renderer.GetActiveCamera()
        position = np.array(cam.GetPosition(), dtype=float)
        focal = np.array(cam.GetFocalPoint(), dtype=float)
        offset = position - focal

        distance = float(np.linalg.norm(offset))
        if distance < self.MIN_DISTANCE:
            distance = self.MIN_DISTANCE

        horizontal = math.hypot(offset[0], offset[1])
        yaw = math.atan2(offset[0], -offset[1])
        pitch = math.atan2(offset[2], horizontal)

        return CameraOrbitState(
            pivot=tuple(focal),
            distance=distance,
            yaw=yaw,
            pitch=pitch,
            view_angle=cam.GetViewAngle(),
        )

    def _apply_orbit(self):
        # INVARIANT: The orbit should never be uninitialized!
        assert self._orbit is not None

        cam = self.renderer.GetActiveCamera()
        cam.SetFocalPoint(*self._orbit.pivot)
        cam.SetPosition(*self._orbit.camera_position())
        cam.SetViewUp(0, 0, 1)
        cam.SetViewAngle(self._orbit.view_angle)

        # Keep the near plane close enough that geometry doesn't disappear
        # when the camera gets close to the pivot.
        distance = self._orbit.distance
        near_clip = max(distance * 0.001, 1e-5)
        far_clip = max(distance * 100.0, near_clip + 1.0)

        cam.SetClippingRange(near_clip, far_clip)

    def _ensure_orbit_active(self):
        """
        Adopt the current camera pose as the orbit base if we're not already
        manipulating it - covers first-ever use and resuming from a planned viewpoint.
        """
        if self._orbit is None:
            self._orbit = self._orbit_from_camera()

    def orbit(self, dx: float, dy: float):
        """
        Rotate around the pivot. Yaw/pitch are independent and clamped.
        """
        self._ensure_orbit_active()

        # INVARIANT: The orbit should never be uninitialized!
        assert self._orbit is not None

        yaw = self._orbit.yaw - dx * self.YAW_SENSITIVITY
        pitch = self._orbit.pitch + dy * self.PITCH_SENSITIVITY
        pitch = max(-self.PITCH_LIMIT, min(self.PITCH_LIMIT, pitch))
        self._orbit = replace(self._orbit, yaw=yaw, pitch=pitch)
        self._apply_orbit()

    def pan(self, dx: float, dy: float):
        """
        Translate the pivot (and camera) along the screen's right/up axes.
        Never changes orientation, and never reads scene bounds.
        """
        self._ensure_orbit_active()

        # INVARIANT: The orbit should never be uninitialized!
        assert self._orbit is not None

        cam = self.renderer.GetActiveCamera()
        matrix = cam.GetViewTransformMatrix()  # VTK's actual camera basis
        right = np.array([matrix.GetElement(0, i) for i in range(3)])
        true_up = np.array([matrix.GetElement(1, i) for i in range(3)])

        # Scale by distance so pan speed feels consistent at any zoom level.
        scale = self._orbit.distance * self.PAN_SENSITIVITY
        offset = (-right * dx + true_up * dy) * scale
        pivot = tuple(np.array(self._orbit.pivot, dtype=float) + offset)
        self._orbit = replace(self._orbit, pivot=pivot)
        self._apply_orbit()

    def dolly(self, amount: float):
        """Move toward/away from the pivot. Positive amount = zoom in."""
        self._ensure_orbit_active()

        # INVARIANT: The orbit should never be uninitialized!
        assert self._orbit is not None

        distance = self._orbit.distance * (1.0 - amount * self.ZOOM_SENSITIVITY)
        distance = max(self.MIN_DISTANCE, distance)
        self._orbit = replace(self._orbit, distance=distance)
        self._apply_orbit()

    # TODO(Adam): This function is currently unused. Use or remove it!
    # def frame_scene(self):
    #     """
    #     Deliberately reframe on current scene bounds (similar to Unity's 'Frame Selected').
    #     This is the only place scene bounds are allowed to affect the camera.
    #     """
    #     self.renderer.ResetCamera()
    #     self._orbit = self._orbit_from_camera()

    # -- Overview --------------------------------------------------------

    def save_overview(self):
        self._orbit = self._orbit_from_camera()

    def show_overview(self):
        """Return to the free-look camera."""
        if self._orbit is None:
            self.save_overview()
        else:
            self._apply_orbit()
