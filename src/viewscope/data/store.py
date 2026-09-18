"""Global application state for the currently loaded scene."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal

from viewscope.camera.structs import CameraInfo
from viewscope.data.scene import SceneData
from viewscope_core import Plan


class SceneStore(QObject):
    """Global application state for the currently loaded scene."""

    scene_loaded = Signal()
    scene_unloaded = Signal()
    scene_changed = Signal()
    plan_changed = Signal(CameraInfo)

    def __init__(self):
        super().__init__()
        self._scene: SceneData | None = None
        self.new_camera_ids: set[str] = set()

    def set_scene(self, scene: SceneData) -> None:
        self._scene = scene
        self.new_camera_ids.clear()

        self.scene_loaded.emit()
        self.scene_changed.emit()
        self.plan_changed.emit(None)

    def clear(self) -> None:
        self._scene = None
        self.new_camera_ids.clear()

        self.scene_unloaded.emit()
        self.scene_changed.emit()
        self.plan_changed.emit(None)

    def add_camera(self, position: tuple[float, float, float], yaw: float, pitch: float):
        if self.scene is None:
            return

        # NOTE(Adam): So vc.Plan is immutable (for some reason).
        #             When adding a new camera, we have to create a completely new Plan.
        old_plan = self.scene.plan

        max_id = max(int(id[2:]) for id in old_plan.ids)
        new_id = f"vp{max_id + 1}"

        info = CameraInfo(
            index=len(old_plan.ids),  # the row the new camera is appended at
            position=np.asarray(position, dtype=float),
            yaw=yaw,
            pitch=pitch,
        )

        self.scene.plan = Plan(
            camera=old_plan.camera,
            ids=old_plan.ids + (new_id,),
            positions=np.concatenate((old_plan.positions, info.position[None, :]), axis=0),
            yaws_deg=np.concatenate((old_plan.yaws_deg, np.array([yaw]))),
            pitches_deg=np.concatenate((old_plan.pitches_deg, np.array([pitch]))),
        )

        self.new_camera_ids.add(new_id)  # NOTE(Azaam): Adds new cameras to this set
        self.scene_changed.emit()
        self.plan_changed.emit(info)

    def ensure_cameras(self, entries) -> tuple[tuple[int, ...], int]:
        """
        Make sure the plan holds every one of these viewpoints.

        `entries` are (id, position, yaw_deg, pitch_deg). Viewpoints the plan
        already has are left exactly as they are; the rest are appended,
        keeping the ids they arrived with. Returns the plan row of every
        entry, in the order they were given, and how many were appended.

        This is what loading a route runs on: the file says which cameras
        should be in the scene, and afterwards they are.
        """
        if self.scene is None:
            return (), 0

        old_plan = self.scene.plan
        row_of = {name: index for index, name in enumerate(old_plan.ids)}

        rows, fresh = [], []
        for name, position, yaw, pitch in entries:
            if name in row_of:
                rows.append(row_of[name])
                continue

            row = len(old_plan.ids) + len(fresh)
            row_of[name] = row
            fresh.append((name, np.asarray(position, dtype=float), float(yaw), float(pitch)))
            rows.append(row)

        if not fresh:
            return tuple(rows), 0

        self.scene.plan = Plan(
            camera=old_plan.camera,
            ids=old_plan.ids + tuple(entry[0] for entry in fresh),
            positions=np.concatenate((old_plan.positions, np.array([entry[1] for entry in fresh]))),
            yaws_deg=np.concatenate((old_plan.yaws_deg, np.array([entry[2] for entry in fresh]))),
            pitches_deg=np.concatenate(
                (old_plan.pitches_deg, np.array([entry[3] for entry in fresh]))
            ),
        )

        first = CameraInfo(
            index=len(old_plan.ids),
            position=fresh[0][1],
            yaw=fresh[0][2],
            pitch=fresh[0][3],
        )
        self.scene_changed.emit()
        self.plan_changed.emit(first)

        return tuple(rows), len(fresh)

    @property
    def scene(self) -> SceneData | None:
        return self._scene

    @property
    def loaded(self) -> bool:
        return self._scene is not None

    @property
    def camera_count(self) -> int:
        if self.scene is None:
            return 0

        return len(self.scene.plan.positions)


# Single global instance of the current SceneData
SCENE_STORE: SceneStore = SceneStore()
