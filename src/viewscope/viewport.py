"""The 3D viewport: a render window plus the views drawn into it."""

from __future__ import annotations

from typing import cast

import vtk
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
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
from viewscope.scene.gizmos import CameraGlyphs, CameraOutline, FloorGrid
from viewscope.scene.stats import FieldStats
from viewscope.scene.views import MeshView, TargetCloudView


class Viewport(QVTKRenderWindowInteractor):
    """
    Renders a bundle and exposes display state as plain method calls.

    Emits `camera_changed` with a CameraInfo, or None for the overview, so
    panels can follow along without reaching into the renderer.
    """

    # Swallow residual noise from the cursor warp during manipulation
    _WARP_ECHO_EPSILON: float = 2.0  # px

    camera_changed = Signal(CameraInfo)
    camera_picked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*BACKGROUND)
        self.GetRenderWindow().AddRenderer(self.renderer)

        self._interactor = self.GetRenderWindow().GetInteractor()
        self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        self._mouse_picker = vtk.vtkPropPicker()
        self._mouse_picker.PickFromListOn()

        self.mesh = None
        self.cloud = None
        self.glyphs = None
        self.camera = None
        self._mode = MODE_ALL
        self._mouse_locked = False
        self._mouse_lock_global_pos = QPoint()
        self._mouse_virtual_local_pos = QPointF()

        # TODO(Azaam): Enable the two lines, when resuming Grid optimization
        # Adding observer only on active camera, for zoom-scale calculation.
        # local_camera = self.renderer.GetActiveCamera()
        # local_camera.AddObserver(vtk.vtkCommand.ModifiedEvent, self._on_camera_modified)

        # TODO(Azaam): Enable when resuming Grid optimization
        # self.initial_camera_distance = self.renderer.GetActiveCamera().GetDistance()
        # self.zoom_distance = 1.0  # The zoom distance from cam to focal point.
        # self.grid_scale = 1.0  # The scale factor for the grid, based on zoom distance.
        # self.grid_visible = True  # Tracking visibility locally to hide grid properly.

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

        self._finalized = False  # see shutdown()

        # FloorGrid configuration. set_scene moves it onto the ground of
        # whichever bundle is loaded, so this is only where it starts.
        self.grid_origin_point = (0.0, 0.0, 0.0)
        self.floor_grid = FloorGrid(self.renderer, 100, self.grid_origin_point)

    # -- Lifecycle -----------------------------------------------------

    def start(self):
        """Call once the window is on screen."""
        self._interactor.Initialize()

    def shutdown(self):
        """Release the GL context explicitly; skipping this crashes on macOS.

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
        self.mesh = MeshView(data.mesh)
        self.cloud = TargetCloudView(data.targets, data.scores)
        self.glyphs = CameraGlyphs(data.plan)

        for view in (self.mesh, self.cloud, self.glyphs):
            view.add_to(self.renderer)

        for glyph_actor in self.glyphs.actors:
            self._mouse_picker.AddPickList(glyph_actor)

        self.grid_origin_point = self._ground_centre(data)
        self.floor_grid.move_to(self.grid_origin_point)

        self.camera = CameraController(self.renderer, YFOV_DEG)
        self.renderer.ResetCamera()
        self.camera.save_overview()
        self.set_mode(self._mode)

    @staticmethod
    def _ground_centre(data: SceneData) -> tuple:
        """The middle of the scene's footprint, at its lowest point."""
        low, high = data.mesh.bounds
        return (float((low[0] + high[0]) / 2), float((low[1] + high[1]) / 2), float(low[2]))

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

    def set_grid_visible(self, visible: bool):
        """Show/Hide the floor grid."""
        # self.grid_visible = visible
        if self.has_scene and self.floor_grid is not None:
            # TODO(Azaam): Enable the segment, when resuming Grid optimization
            # if self.grid_visible:
            #     self.floor_grid.remove_from(self.renderer)
            #     self.floor_grid = FloorGrid(
            #         self.renderer, 100, self.grid_origin_point, self.grid_scale
            #     )
            # else:
            #     self.floor_grid.set_visible(visible)
            self.floor_grid.set_visible(visible)
            self.render()

    # -- Camera --------------------------------------------------------

    def show_overview(self):
        if self.has_scene and self.camera is not None:
            self._moved(self.camera.show_overview())

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
            for glyph_actor in self.glyphs.actors:
                self._mouse_picker.DeletePickList(glyph_actor)

            self.glyphs.remove_from(self.renderer)

        self.glyphs = CameraGlyphs(SCENE_STORE.scene.plan)
        self.glyphs.add_to(self.renderer)

        for glyph_actor in self.glyphs.actors:
            self._mouse_picker.AddPickList(glyph_actor)

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
        """
        Lock mouse on Right Click, Left Click & Middle Click, and handle mouse-picking dispatch.
        """
        # NOTE(Adam): Early-return here handles camera-click vs viewport manip on left-click
        if (ev.button() == Qt.MouseButton.LeftButton) and self._pick_camera_glyph(ev):
            super().mousePressEvent(ev)
            return

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
        if not self._mouse_locked:
            super().mouseMoveEvent(ev)
            return

        anchor = QPointF(self._mouse_lock_global_pos)
        current_global = ev.globalPosition()
        delta = current_global - anchor

        # Swallow the warp's own echo (and any sub-pixel OS noise) without
        # discarding a whole event; real motion merged into a compressed
        # event still gets through, so nothing gets batched/skipped.
        if (abs(delta.x()) <= self._WARP_ECHO_EPSILON) and (
            abs(delta.y()) <= self._WARP_ECHO_EPSILON
        ):
            return

        # Accumulate relative delta onto virtual local position
        self._mouse_virtual_local_pos += delta

        # Synthesize event with accumulated position so VTK trackball moves smoothly
        fake_ev = QMouseEvent(
            ev.type(),
            self._mouse_virtual_local_pos,
            ev.globalPosition(),
            ev.button(),
            ev.buttons(),
            ev.modifiers(),
        )

        QCursor.setPos(self._mouse_lock_global_pos)
        super().mouseMoveEvent(fake_ev)

    def _mouse_lock_enter(self, ev: QMouseEvent):
        self._mouse_locked = True
        self._mouse_lock_global_pos = ev.globalPosition().toPoint()

        # Virtual position starts at real initial position and grows infinitely.
        # This position is kept as a float to avoid rounding jitter.
        self._mouse_virtual_local_pos = ev.position()
        self.HideCursor()

    def _mouse_lock_exit(self):
        self._mouse_locked = False

        # Restore cursor visibility and position
        self.ShowCursor()
        QCursor.setPos(self._mouse_lock_global_pos)

    def _pick_camera_glyph(self, ev: QMouseEvent) -> bool:
        """
        Selects the camera from the camera glyph hovered by the mouse cursor.
        Returns True if a camera was under the mouse and selected, False otherwise.
        """
        if self.glyphs is None:
            return False

        # NOTE(Adam): Qt uses the top-left origin.
        #             VTK uses OpenGL coordinates - bottom-left origin.
        dpr = self.devicePixelRatioF()  # Handle window DPI scaling
        x = int(ev.position().x() * dpr)
        y = self.GetRenderWindow().GetSize()[1] - int(ev.position().y() * dpr) - 1
        self._mouse_picker.Pick(x, y, 0, self.renderer)

        actor = self._mouse_picker.GetActor()
        if actor is None:
            return False

        camera_id = self.glyphs.camera_id_of_actor(actor)
        if camera_id is None:
            return False

        print(f"Selected camera: {camera_id}")
        self.camera_picked.emit(camera_id)

        return True

    # TODO(Azaam): Uncomment method, when resuming Grid optimization
    # def _on_camera_modified(self, obj, event) -> None:
    #     """Event handler for calculate zoom level + grid scale, and applying it to grid actor.
    #     The zoom level is based on cameras distance to focal point.
    #     Grid Scale changes whenever the distance variable changes by a factor of 10."""
    #     active_camera = self.renderer.GetActiveCamera()
    #     distance = active_camera.GetDistance()  # From camera to focal point.

    #     if distance == self.zoom_distance:
    #         return  # Exit handler if no "zooming" was performed.
    #     self.zoom_distance = distance

    #     # - Change scale in steps of powers-of-10
    #     raw_scale = distance / self.initial_camera_distance
    #     exponent = floor(log10(raw_scale))
    #     zoom_scale = 1.5**exponent  # Scale factor based on distance
    #     # Used Deepseek for the calculation of the scale factor. (I changed bases though)

    #     if zoom_scale == self.grid_scale:
    #         return  # Exit handler if in same scale bucket/step.
    #     self.grid_scale = zoom_scale  # Update grid scale based on zoom scale

    #     ## Rebuild grid in scene
    #     if self.floor_grid is not None:
    #         self.floor_grid.remove_from(self.renderer)  # Remove old grid
    #         if self.grid_visible:  # Only build if the checkbox is checked in DisplayPanel
    #             self.floor_grid = FloorGrid(
    #                 self.renderer, 100, self.grid_origin_point, self.grid_scale
    #             )
