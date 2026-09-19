"""The 3D viewport: for camera povs. The final, exported images will be rendered from this view."""

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
    MODE_TEXTURED,
    YFOV_DEG,
)
from viewscope.data.scene import SceneData
from viewscope.scene.photo_mesh import PhotoMesh
from viewscope.scene.views import MeshView


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
        self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleUser())  # Disable all input

        self.mesh = None
        self.camera = None

        self._simple_mesh = None
        self._photo_mesh = None

        self._render_mode = MODE_TEXTURED
        self._finalized = False

    # -- Lifecycle -----------------------------------------------------

    def start(self):
        """Call once the window is on screen."""
        self._interactor.Initialize()

    def shutdown(self):
        """
        Release the GL context explicitly; skipping this crashes on macOS.

        Runs at most once: closing the window and later destroying it would
        otherwise finalize the same render window twice, which frees the same
        pointer twice.
        """
        if self._finalized:
            return

        self._finalized = True
        self.Finalize()

    def render(self):
        self.GetRenderWindow().Render()

    # -- Scene ---------------------------------------------------------

    def set_scene(self, data: SceneData):
        # Only render the Mesh
        self.mesh = MeshView(data.mesh)
        self.mesh.add_to(self.renderer)

        self._simple_mesh = self.mesh
        self._photo_mesh = None

        self.camera = CameraController(self.renderer, YFOV_DEG)
        self.renderer.ResetCamera()
        self.camera.save_overview()

        self.set_render_mode(self._render_mode)
        self._apply_render_mode()

    @property
    def has_scene(self) -> bool:
        return self.mesh is not None

    # -- Display state -------------------------------------------------

    def set_render_mode(self, mode: str):
        if self._render_mode == mode:
            return

        if not self.has_scene:
            return

        self._render_mode = mode
        self._apply_render_mode()

    def _apply_render_mode(self):
        """
        Dress whichever mesh is on screen in the current mode.
        Separate from set_mode because the mode outlives the mesh: the
        full-resolution model arrives seconds after the scene does and has to
        come up wearing what the simplified one was wearing.
        """
        mode = self._render_mode
        show_mesh = mode in (MODE_TEXTURED, MODE_GEOMETRY, MODE_ALL)

        if self.mesh is not None:
            self.mesh.set_visible(show_mesh)
            if mode == MODE_GEOMETRY:
                self.mesh.show_geometry()
            elif show_mesh:
                self.mesh.show_textured()

        self.render()

    # -- Photo Mesh ------------------------------------------------------

    def set_photo_mesh(self, photo: PhotoMesh):
        """
        Swap the simplified mesh for the model the photos are taken from.
        The camera does not move: the pose it holds is a viewpoint out of the
        plan, and both meshes are in the same frame, so the same pose frames
        the same shot in more detail. The window reads the model once and
        hands it to whichever panels want it.
        """
        if not self.has_scene:
            return

        if self.mesh is not None:
            self.mesh.remove_from(self.renderer)

        self._photo_mesh = photo
        self.mesh = photo
        photo.add_to(self.renderer)

        # This first frame carries the textures up to the GPU and is the slow
        # one; every frame after it is drawn at the usual rate.
        self._apply_render_mode()

    # -- Camera --------------------------------------------------------

    def show_overview(self):
        # INVARIANT: Camera should not be uninitialized at this stage!
        assert self.camera is not None
        self._moved(self.camera.show_overview())

    def show_camera(self, index: int):
        # INVARIANT: Camera should not be uninitialized at this stage!
        assert self.camera is not None
        self._moved(self.camera.show(index))

    def next_camera(self):
        # INVARIANT: Camera should not be uninitialized at this stage!
        assert self.camera is not None
        self._moved(self.camera.step(1))

    def prev_camera(self):
        # INVARIANT: Camera should not be uninitialized at this stage!
        assert self.camera is not None
        self._moved(self.camera.step(-1))

    def _moved(self, info: CameraInfo | None):
        self.camera_changed.emit(info)
        self.render()

    def on_camera_moved(self, index: int):
        """
        Triggers a reframe of a selected camera,
        when SCENE_STORE's move_camera method is executed.
        This viewport will change and re-render from the view of the moving camera.
        """
        if self.camera is None or self.camera.index != index:
            return

        self._moved(self.camera.show(index))
