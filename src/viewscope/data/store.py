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

    def set_scene(self, scene: SceneData) -> None:
        self._scene = scene
        self.scene_loaded.emit()
        self.scene_changed.emit()
        self.plan_changed.emit(None)

    def clear(self) -> None:
        self._scene = None
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

        self.scene_changed.emit()
        self.plan_changed.emit(info)

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
