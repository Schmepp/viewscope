"""The 3D viewport: a render window plus the views drawn into it."""

from __future__ import annotations  # noqa: E402

# Must be set before the Qt widget module is imported, so VTK binds to the
# same Qt binding we are using rather than guessing.
import vtkmodules.qt  # noqa: E402

vtkmodules.qt.PyQtImpl = "PySide6"

import vtk  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402
from vtkmodules.qt.QVTKRenderWindowInteractor import (  # noqa: E402
    QVTKRenderWindowInteractor,
)
from vtkmodules.vtkInteractionWidgets import vtkCameraOrientationWidget  # noqa: E402

from .camera import CameraController  # noqa: E402
from .config import (  # noqa: E402
    BACKGROUND,
    MODE_ALL,
    MODE_GEOMETRY,
    MODE_TARGETS,
    MODE_TEXTURED,
    YFOV_DEG,
)
from .loading import SceneData  # noqa: E402
from .scene import CameraGlyphs, MeshView, TargetCloudView  # noqa: E402


class Viewport(QVTKRenderWindowInteractor):
    """Renders a bundle and exposes display state as plain method calls.

    Emits `camera_changed` with a CameraInfo, or None for the overview, so
    panels can follow along without reaching into the renderer.
    """

    camera_changed = Signal(object)

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

        # Camera Orientation Widget configuration
        self.orientation_widget = vtkCameraOrientationWidget()
        self.orientation_widget.SetParentRenderer(self.renderer)
        # Representation = the widget that's drawn in render window
        representation = self.orientation_widget.GetRepresentation()
        representation.AnchorToUpperLeft()  # type: ignore
        self.set_camera_orientation_visible(True)

    # -- lifecycle -----------------------------------------------------

    def start(self):
        """Call once the window is on screen."""
        self._interactor.Initialize()

    def shutdown(self):
        # Release the GL context explicitly; skipping this crashes on macOS.

        self.Finalize()

    def render(self):
        self.GetRenderWindow().Render()

    # -- scene ---------------------------------------------------------

    def set_scene(self, data: SceneData):
        self.mesh = MeshView(data.mesh)
        self.cloud = TargetCloudView(data.targets, data.scores)
        self.glyphs = CameraGlyphs(data.plan)

        for view in (self.mesh, self.cloud, self.glyphs):
            view.add_to(self.renderer)

        self.camera = CameraController(
            self.renderer, data.plan, data.diagonal, YFOV_DEG
        )

        self.renderer.ResetCamera()
        self.camera.save_overview()
        self.set_mode(self._mode)

    @property
    def has_scene(self) -> bool:
        return self.mesh is not None

    # -- display state -------------------------------------------------

    def set_mode(self, mode: str):
        self._mode = mode
        if not self.has_scene:
            return

        show_mesh = mode in (MODE_TEXTURED, MODE_GEOMETRY, MODE_ALL)
        self.mesh.set_visible(show_mesh)
        self.cloud.set_visible(mode in (MODE_TARGETS, MODE_ALL))

        if mode == MODE_GEOMETRY:
            self.mesh.show_geometry()
        elif show_mesh:
            self.mesh.show_textured()

        self.render()

    def set_scalar_field(self, field: str):
        """Returns FieldStats, or None when the bundle has no scores."""
        if not self.has_scene:
            return None
        stats = self.cloud.set_field(field)
        self.render()
        return stats

    def set_point_size(self, size: int):
        if self.has_scene:
            self.cloud.set_point_size(size)
            self.render()

    def set_glyphs_visible(self, visible: bool):
        if self.has_scene:
            self.glyphs.set_visible(visible)
            self.render()

    # -- camera --------------------------------------------------------

    def show_overview(self):
        if self.has_scene:
            self._moved(self.camera.show_overview())

    def show_camera(self, index: int):
        if self.has_scene:
            self._moved(self.camera.show(index))

    def next_camera(self):
        if self.has_scene:
            self._moved(self.camera.step(1))

    def prev_camera(self):
        if self.has_scene:
            self._moved(self.camera.step(-1))

    def _moved(self, info):
        self.glyphs.set_active(None if info is None else info.index)
        self.camera_changed.emit(info)
        self.render()

    def set_camera_orientation_visible(self, visible: bool):  # orientation widget
        if visible:
            self.orientation_widget.On()
        else:
            self.orientation_widget.Off()
        self.render()

    def toggle_camera_orientation_visible(self):
        current_visibility = self.orientation_widget.GetEnabled()
        self.set_camera_orientation_visible(not current_visibility)
        # print(str(current_visibility) + " is widget visibility")
