"""Global application state for the currently loaded scene."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from viewscope.data.scene import SceneData


class SceneStore(QObject):
    """Global application state for the currently loaded scene."""

    scene_loaded = Signal()
    scene_unloaded = Signal()
    scene_changed = Signal()

    def __init__(self):
        super().__init__()
        self._scene: SceneData | None = None

    @property
    def scene(self) -> SceneData | None:
        return self._scene

    @property
    def loaded(self) -> bool:
        return self._scene is not None

    def set_scene(self, scene: SceneData) -> None:
        self._scene = scene
        self.scene_loaded.emit()
        self.scene_changed.emit()

    def clear(self) -> None:
        self._scene = None
        self.scene_unloaded.emit()
        self.scene_changed.emit()


# Single global instance of the current SceneData
SCENE_STORE: SceneStore = SceneStore()
