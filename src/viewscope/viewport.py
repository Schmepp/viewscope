"""The 3D viewport: a render window plus the views drawn into it."""

from __future__ import annotations

from typing import cast

import vtk
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from vtkmodules.qt.QVTKRenderWindowInteractor import (
    QVTKRenderWindowInteractor,
)
from vtkmodules.vtkInteractionWidgets import (
    vtkCameraOrientationRepresentation,
    vtkCameraOrientationWidget,
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
from viewscope.scene import CameraGlyphs, CameraOutline, FieldStats, MeshView, TargetCloudView


class Viewport(QVTKRenderWindowInteractor):
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
        self._mouse_locked = False
        self._ignore_next_mouse_move = False
        self._mouse_lock_position = QPoint()
        self._mouse_lock_global_pos = QPoint()
        self._mouse_virtual_local_pos = QPoint()

        self.selected_outline = CameraOutline()
        self.selected_camera_pos = (0, 0, 0)

        # Camera Orientation Widget configuration
        self.orientation_widget = vtkCameraOrientationWidget()
        self.orientation_widget.SetParentRenderer(self.renderer)

        # Representation - the widget that's drawn in render window
        representation = cast(
            vtkCameraOrientationRepresentation,
            self.orientation_widget.GetRepresentation(),
        )
        representation.AnchorToUpperLeft()

        self.set_camera_orientation_visible(True)

    # -- Lifecycle -----------------------------------------------------

    def start(self):
        """Call once the window is on screen."""
        self._interactor.Initialize()

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

    def set_scalar_field(self, field: str) -> FieldStats | None:
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

    def on_camera_changed(self):
        """Update the highlighted camera."""
        self.selected_outline.remove_from(self.renderer)
        if self.selected_camera_pos != (0, 0, 0):
            self.selected_outline.build(self.renderer, self.selected_camera_pos)

        self.render()

    def on_plan_changed(self):
        """Rebuild the camera glyphs for the current plan."""
        if SCENE_STORE.scene is None:
            return

        # NOTE(Adam): The only renderer objects that need to be fully rebuilt
        #             when the plan changes are the camera glyphs. The mesh and
        #             cloud are unaffected by the plan.
        if self.glyphs is not None:
            self.glyphs.remove_from(self.renderer)

        self.glyphs = CameraGlyphs(SCENE_STORE.scene.plan)
        self.glyphs.add_to(self.renderer)

        self.render()

    def set_selected_camera_position(self, info: CameraInfo | None):
        if info is not None:
            self.selected_camera_pos = (
                float(info.position[0]),
                float(info.position[1]),
                float(info.position[2]),
            )

    def _moved(self, info: CameraInfo | None):
        if self.glyphs is not None:
            self.glyphs.set_active(None if info is None else info.index)

        self.camera_changed.emit(info)
        self.render()

    def set_camera_orientation_visible(self, visible: bool):
        if visible:
            self.orientation_widget.On()
        else:
            self.orientation_widget.Off()
        self.render()

    def toggle_camera_orientation_visible(self):
        current_visibility = self.orientation_widget.GetEnabled()
        self.set_camera_orientation_visible(not current_visibility)

    # -- Mouse --------------------------------------------------------

    def mousePressEvent(self, ev: QMouseEvent):
        """Lock mouse on Right Click, Left Click & Middle Click."""
        if (
            ev.button()
            in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton)
            and not self._mouse_locked
        ):
            self._mouse_lock_enter(ev)

        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        """Unlock the mouse when all tracked mouse buttons have been released."""
        super().mouseReleaseEvent(ev)

        if self._mouse_locked and not (
            ev.buttons()
            & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton)
        ):
            self._mouse_lock_exit()

    def mouseMoveEvent(self, ev: QMouseEvent):
        """
        Handle mouse movements during viewport manipulation when the mouse is locked.

        When the mouse is locked during active interaction (e.g., panning or rotating),
        this method intercepts the OS move event to accumulate virtual positional deltas
        and forwards synthetic events to VTK's interactor style. The physical OS cursor
        is reset back to its initial anchor position to allow infinite range-of-motion
        without running off-screen.
        """
        if self._ignore_next_mouse_move:
            self._ignore_next_mouse_move = False
            return

        if self._mouse_locked:
            current_global = ev.globalPosition().toPoint()
            delta = current_global - self._mouse_lock_global_pos

            if not delta.isNull():
                # Accumulate relative delta onto virtual local position
                self._mouse_virtual_local_pos += delta

                # Synthesize event with accumulated position so VTK trackball moves smoothly
                fake_ev = QMouseEvent(
                    ev.type(),
                    self._mouse_virtual_local_pos.toPointF(),
                    ev.globalPosition(),
                    ev.button(),
                    ev.buttons(),
                    ev.modifiers(),
                )

                # Reset physical cursor back to anchor point
                self._ignore_next_mouse_move = True
                QCursor.setPos(self._mouse_lock_global_pos)

                # Forward accumulated delta event to VTK interactor
                super().mouseMoveEvent(fake_ev)
                return

        super().mouseMoveEvent(ev)

    def _mouse_lock_enter(self, ev: QMouseEvent):
        self._mouse_locked = True
        self._mouse_lock_position = ev.position().toPoint()
        self._mouse_lock_global_pos = ev.globalPosition().toPoint()

        # Virtual position starts at real initial position and grows infinitely
        self._mouse_virtual_local_pos = QPoint(self._mouse_lock_position)
        self._ignore_next_mouse_move = False

        self.HideCursor()

    def _mouse_lock_exit(self):
        self._mouse_locked = False
        self._ignore_next_mouse_move = False

        # Restore cursor visibility and position
        self.ShowCursor()
        QCursor.setPos(self._mouse_lock_global_pos)
