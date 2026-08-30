"""The 3D viewport: for camera povs"""

from __future__ import annotations

import vtk
from PySide6.QtCore import Signal
from vtkmodules.qt.QVTKRenderWindowInteractor import (
    QVTKRenderWindowInteractor,
)

import viewscope.qt  # noqa: F401
from viewscope.camera.controller import CameraController
from viewscope.camera.structs import CameraInfo
from viewscope.config import (
    BACKGROUND,
    MODE_ALL,
    MODE_GEOMETRY,
    MODE_TARGETS,
    MODE_TEXTURED,
    YFOV_DEG,
)
from viewscope.data.scene import SceneData
from viewscope.data.store import SCENE_STORE
from viewscope.scene import CameraGlyphs, MeshView, TargetCloudView


class CameraViewport(QVTKRenderWindowInteractor):
    """
    Renders a bundle and exposes display state as plain method calls.

    Emits `camera_changed` with a CameraInfo, or None for the overview, so
    panels can follow along without reaching into the renderer.
    """

    camera_changed = Signal(CameraInfo)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*BACKGROUND)
        self.GetRenderWindow().AddRenderer(self.renderer)

        self._interactor = self.GetRenderWindow().GetInteractor()
        self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        self.mesh = None
        self.cloud = None
        self.glyphs = None
        self.camera = None
        self._mode = MODE_ALL

    # -- Lifecycle -----------------------------------------------------

    def start(self):
        """Call once the window is on screen."""
        self._interactor.Initialize()
        self._interactor.Disable()  # Disable the interactor entirely

    def shutdown(self):
        """Release the GL context explicitly; skipping this crashes on macOS."""
        self.Finalize()

    def render(self):
        self.GetRenderWindow().Render()

    # -- Scene ---------------------------------------------------------

    def set_scene(self, data: SceneData):
        self.mesh = MeshView(data.mesh)
        self.cloud = TargetCloudView(data.targets, data.scores)
        self.glyphs = CameraGlyphs(data.plan)

        for view in (self.mesh, self.cloud, self.glyphs):
            view.add_to(self.renderer)

        self.camera = CameraController(self.renderer, YFOV_DEG)
        self.renderer.ResetCamera()
        self.camera.save_overview()
        self.set_mode(self._mode)

    @property
    def has_scene(self) -> bool:
        return self.mesh is not None

    # -- Display state -------------------------------------------------

    def set_mode(self, mode: str):
        if self._mode == mode:
            return

        if not self.has_scene:
            return

        self._mode = mode
        show_mesh = mode in (MODE_TEXTURED, MODE_GEOMETRY, MODE_ALL)

        if self.mesh is not None:
            self.mesh.set_visible(show_mesh)

            if mode == MODE_GEOMETRY:
                self.mesh.show_geometry()
            elif show_mesh:
                self.mesh.show_textured()

        if self.cloud is not None:
            self.cloud.set_visible(mode in (MODE_TARGETS, MODE_ALL))

        self.render()

    def set_scalar_field(self, field: str):
        """Returns FieldStats, or None when the bundle has no scores."""
        if not self.has_scene:
            return None

        stats = None
        if self.cloud is not None:
            stats = self.cloud.set_field(field)

        self.render()
        return stats

    def set_point_size(self, size: int):
        if self.has_scene and self.cloud is not None:
            self.cloud.set_point_size(size)
            self.render()

    def set_glyphs_visible(self, visible: bool):
        if self.has_scene and self.glyphs is not None:
            self.glyphs.set_visible(visible)
            self.render()

    def set_occlusion_mask(self, mask):
        """Paint the targets one camera can see; None restores the field colours."""
        if self.has_scene and self.cloud is not None:
            self.cloud.set_occlusion(mask)
            self.render()

    # -- Camera --------------------------------------------------------

    def show_overview(self):
        if self.has_scene and self.camera is not None:
            self._moved(self.camera.show_overview())

    def show_camera(self, index: int):
        if self.has_scene and self.camera is not None:
            self._moved(self.camera.show(index))

    def next_camera(self):
        if self.has_scene and self.camera is not None:
            self._moved(self.camera.step(1))

    def prev_camera(self):
        if self.has_scene and self.camera is not None:
            self._moved(self.camera.step(-1))

    # TODO(Adam): Fix this function.
    #             See window.py:_on_camera_changed() for details.
    def on_camera_changed(self):
        """Update the camera glyphs."""
        if SCENE_STORE.scene is None:
            return

        scene = SCENE_STORE.scene
        self.glyphs = CameraGlyphs(scene.plan)

        for view in (self.mesh, self.cloud, self.glyphs):
            if view is not None:
                view.add_to(self.renderer)

        self.camera = CameraController(self.renderer, YFOV_DEG)
        self.renderer.ResetCamera()
        self.camera.save_overview()

    def _moved(self, info: CameraInfo | None):
        if self.glyphs is not None:
            self.glyphs.set_active(None if info is None else info.index)

        self.camera_changed.emit(info)
        self.render()
