"""The 3D viewport: a render window plus the views drawn into it."""

from __future__ import annotations

from typing import cast

import numpy as np
import vtk
from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QMouseEvent, QWheelEvent
from vtkmodules.qt.QVTKRenderWindowInteractor import (
    QVTKRenderWindowInteractor,
)
from vtkmodules.vtkInteractionWidgets import (
    vtkCameraOrientationRepresentation,
    vtkCameraOrientationWidget,
)

import viewscope.qt  # noqa: F401
from viewscope.camera.structs import CameraInfo
from viewscope.config import (
    BACKGROUND,
    MODE_ALL,
    MODE_GEOMETRY,
    MODE_TARGETS,
    MODE_TEXTURED,
    PICK_DRAG_SLOP_PX,
    PICK_TARGET_RADIUS_PX,
    YFOV_DEG,
    OverlayOptions,
)
from viewscope.data.scene import SceneData
from viewscope.data.store import SCENE_STORE
from viewscope.scene.camera import CameraMode, SceneCameraController
from viewscope.scene.gizmos import CameraGlyphs, CameraModeGizmo, CameraOutline, FloorGrid
from viewscope.scene.stats import FieldStats
from viewscope.scene.target_gizmos import TargetOverlay, observer_colour, weight_lut
from viewscope.scene.target_report import TargetReport
from viewscope.scene.views import MeshView, TargetCloudView


class Viewport(QVTKRenderWindowInteractor):
    """
    Renders a bundle and exposes display state as plain method calls.

    Emits `camera_changed` with a CameraInfo, or None for the overview, so
    panels can follow along without reaching into the renderer.
    """

    # Swallow residual noise from the cursor warp during manipulation
    _WARP_ECHO_EPSILON: float = 2.0  # px
    _ZOOM_NOTCH_SENSITIVITY: float = 20
    _CAMERA_MODE_TRANSITION_DURATION_MS: float = 500.0

    camera_changed = Signal(CameraInfo)
    camera_picked = Signal(int)
    #: A surface target was clicked, by its row in the target cloud.
    target_picked = Signal(int)
    #: A click landed on nothing, so whatever was picked should be let go.
    target_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*BACKGROUND)
        self.GetRenderWindow().AddRenderer(self.renderer)

        self._interactor = self.GetRenderWindow().GetInteractor()
        self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleUser())

        self._mouse_picker = vtk.vtkPropPicker()
        self._mouse_picker.PickFromListOn()

        # Targets are picked off the surface they sit on, so a click never
        # reaches a target on the far side of the model. With the mesh hidden
        # there is nothing to hide behind, and the cloud is picked directly.
        self._surface_picker = vtk.vtkCellPicker()
        self._surface_picker.PickFromListOn()
        self._point_picker = vtk.vtkPointPicker()
        self._point_picker.PickFromListOn()

        self.mesh = None
        self.cloud = None
        self.glyphs = None
        self.camera = None

        self._camera_mode = CameraMode.LOOK_AT
        self._render_mode = MODE_ALL

        self._targets = None
        self._overlay = TargetOverlay()
        #: The same table the overlay's rays and scalar bar read, so a camera
        #: glyph and the ray out to it land on one colour.
        self._weight_lut = weight_lut()
        self._mode = MODE_ALL

        self._camera_mode = CameraMode.LOOK_AT
        self._render_mode = MODE_ALL
        self._mouse_locked = False
        self._mouse_lock_global_pos = QPoint()
        self._mouse_virtual_local_pos = QPointF()

        # Where the gesture started, and how far it has travelled since. A
        # left click that never travels is a pick; one that does is the user
        # swinging the view around, and picks nothing.
        self._press_position = QPointF()
        self._picked_glyph = False
        self._drag_px = 0.0

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
        self.orientation_widget.AddObserver(
            vtk.vtkCommand.InteractionEvent, self._on_camera_moved_external
        )
        self.orientation_widget.AddObserver(
            vtk.vtkCommand.EndInteractionEvent, self._on_camera_moved_external
        )

        # Representation - the widget that's drawn in render window
        representation = cast(
            vtkCameraOrientationRepresentation,
            self.orientation_widget.GetRepresentation(),
        )
        representation.AnchorToUpperLeft()

        self.set_camera_orientation_visible(True)

        # CameraMode gizmo configuration
        self.camera_mode_gizmo = CameraModeGizmo(self)
        self.camera_mode_gizmo.mode_changed.connect(self.set_scene_camera_mode)
        self.camera_mode_gizmo.raise_()

        # Animates the LOOK_AT camera into place after leaving TRACKBALL mode,
        # rather than snapping to stale orbit state on the next interaction.
        self._mode_transition_timer = QTimer(self)
        self._mode_transition_timer.setInterval(16)  # Assuming ~60fps
        self._mode_transition_timer.timeout.connect(self._on_camera_mode_transition_tick)
        self._mode_transition_elapsed = QElapsedTimer()
        self._mode_transition_start = None

        self._finalized = False  # See shutdown()

        # FloorGrid configuration. set_scene moves it onto the ground of
        # whichever bundle is loaded, so this is only where it starts.
        self.grid_origin_point = (0.0, 0.0, 0.0)
        self.floor_grid = FloorGrid(self.renderer, 100, self.grid_origin_point)

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
        self.mesh = MeshView(data.mesh)
        self.cloud = TargetCloudView(data.targets, data.scores)

        for view in (self.mesh, self.cloud):
            view.add_to(self.renderer)

        self._rebuild_glyphs(data.plan)

        self._targets = np.asarray(data.targets, dtype=np.float64)
        self._surface_picker.AddPickList(self.mesh.actor)
        self._point_picker.AddPickList(self.cloud.actor)
        self._mouse_picker.AddPickList(self.mesh.actor)
        for glyph_actor in self.glyphs.actors:
            self._mouse_picker.AddPickList(glyph_actor)

        self.grid_origin_point = self._ground_centre(data)
        self.floor_grid.move_to(self.grid_origin_point)

        self.camera = SceneCameraController(self.renderer, YFOV_DEG)
        self.renderer.ResetCamera()
        self.camera.save_overview()
        self.set_render_mode(self._render_mode)

    @staticmethod
    def _ground_centre(data: SceneData) -> tuple:
        """The middle of the scene's footprint, at its lowest point."""
        low, high = data.mesh.bounds
        return (float((low[0] + high[0]) / 2), float((low[1] + high[1]) / 2), float(low[2]))

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

    def set_route_selection(self, selected: set[int] | None, shown: set[str] | None = None):
        """Paint the route on the camera glyphs; None gives their colours back.

        `shown`, when given, is the plan ids of the only cameras drawn at all:
        every other one in the scene is switched off rather than dimmed.
        """
        if self.has_scene and self.glyphs is not None:
            self.glyphs.set_route(selected, shown)
            self.render()

    # -- Target inspection ---------------------------------------------

    def show_target_overlay(
        self,
        report: TargetReport,
        camera_positions,
        diagonal: float,
        options: OverlayOptions,
    ):
        """Draw the picked target's sector rose and the rays out to its observers."""
        if not self.has_scene:
            return

        self._overlay.show(self.renderer, report, camera_positions, diagonal, options)
        self._colour_observers(report, options.colour_by)
        self.render()

    def clear_target_overlay(self):
        """Take the target overlay down, leaving the rest of the scene alone."""
        self._overlay.clear()
        self.glyphs.set_observer_colours(None)
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

    def on_camera_changed(self, info: CameraInfo | None):
        """Update the highlighted camera. Change its colour to Gold, build outline around it."""
        # INVARIANT: The glyphs should not be uninitialized at this stage!
        assert self.glyphs is not None

        self.glyphs.set_selected(None if info is None else info.index)
        self.selected_outline.remove_from(self.renderer)

        if info is not None:
            self.set_selected_camera_position(info)

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
        self._rebuild_glyphs(SCENE_STORE.scene.plan)
        self.render()

    def _rebuild_glyphs(self, plan):
        """Put one frustum per viewpoint in the scene, and only one.

        The old actors come off the renderer first. Both the scene load and a
        plan change come through here, and they overlap: the store announces
        the plan before set_scene runs, so a set of glyphs is already in the
        renderer by the time the scene arrives. Left there, that set is drawn
        for the life of the window while every route colour and every
        visibility switch lands on the set that replaced it.
        """
        if self.glyphs is not None:
            for glyph_actor in self.glyphs.actors:
                self._mouse_picker.DeletePickList(glyph_actor)

            self.glyphs.remove_from(self.renderer)

        self.glyphs = CameraGlyphs(plan)
        self.glyphs.add_to(self.renderer)

        for glyph_actor in self.glyphs.actors:
            self._mouse_picker.AddPickList(glyph_actor)

    def set_selected_camera_position(self, info: CameraInfo | None):
        if info is not None:
            self.selected_camera_pos = (
                float(info.position[0]),
                float(info.position[1]),
                float(info.position[2]),
            )

    def set_camera_orientation_visible(self, visible: bool):
        if visible:
            self.orientation_widget.On()
        else:
            self.orientation_widget.Off()

        self.render()

    def toggle_camera_orientation_visible(self):
        current_visibility = self.orientation_widget.GetEnabled()
        self.set_camera_orientation_visible(not current_visibility)

    def set_scene_camera_mode(self, mode: CameraMode):
        # INVARIANT: Camera cannot be null!
        assert self.camera is not None

        if mode == self._camera_mode:
            return

        prev_mode = self._camera_mode
        self._camera_mode = mode

        if self._camera_mode is CameraMode.TRACKBALL:
            self._cancel_camera_mode_transition()
            self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        else:
            self._interactor.SetInteractorStyle(vtk.vtkInteractorStyleUser())
            if prev_mode is CameraMode.TRACKBALL:
                self._begin_camera_mode_transition()

        self.camera_mode_gizmo.set_current_mode(mode)
        self.render()

    def _moved(self, info: CameraInfo | None):
        if self.glyphs is not None:
            self.glyphs.set_active(None if info is None else info.index)

        self.camera_changed.emit(info)
        self.render()

    def _begin_camera_mode_transition(self):
        """
        Animate from wherever trackball left the camera into the nearest
        pose the look-at model can represent (same position/pivot, roll
        discarded), instead of snapping there on the next orbit/pan/dolly.
        """
        # INVARIANT: Camera cannot be null!
        assert self.camera is not None

        self._mode_transition_start = self.camera.begin_transition_to_orbit()
        self._mode_transition_elapsed.restart()
        self._mode_transition_timer.start()

    def _cancel_camera_mode_transition(self):
        if self._mode_transition_timer.isActive():
            self._mode_transition_timer.stop()
            self._mode_transition_start = None

    def _on_camera_moved_external(self, obj=None, event=None):
        """
        Resync SceneCameraController after something outside it (the
        orientation widget, a planned-viewpoint jump, etc.) moves the VTK
        camera directly.
        """
        # INVARIANT: Camera cannot be null!
        assert self.camera is not None

        self.camera.sync_from_camera()
        self.render()

    def _on_camera_mode_transition_tick(self):
        """Lerp the transition animation."""
        # INVARIANT: Camera cannot be null!
        assert self.camera is not None

        if self._mode_transition_start is None:
            self._mode_transition_timer.stop()
            return

        t = self._mode_transition_elapsed.elapsed() / self._CAMERA_MODE_TRANSITION_DURATION_MS
        if t >= 1.0:
            self.camera.finish_transition()
            self._mode_transition_timer.stop()
            self._mode_transition_start = None
        else:
            self.camera.apply_transition(self._mode_transition_start, self._smoothstep(t))

        self.render()

    @staticmethod
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    # -- Mouse --------------------------------------------------------

    def mousePressEvent(self, ev: QMouseEvent):
        """
        Lock mouse on Right Click, Left Click & Middle Click, and handle mouse-picking dispatch.
        """
        # Where the gesture started, and how far it has travelled since. A
        # left click that never travels is a pick; one that does is the user
        # swinging the view around, and picks nothing.
        self._press_position = ev.position()
        self._drag_px = 0.0
        self._picked_glyph = False

        # NOTE(Adam): Early-return here handles camera-click vs viewport manip on left-click
        if (ev.button() == Qt.MouseButton.LeftButton) and self._pick_camera_glyph(ev):
            self._picked_glyph = True
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

        if (
            ev.button() == Qt.MouseButton.LeftButton
            and not self._picked_glyph
            and self._drag_px <= PICK_DRAG_SLOP_PX
        ):
            self._pick_target(self._press_position)

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

        # How far the gesture has travelled, past the warp echo: what tells a
        # click meant as a pick from one meant to swing the view around.
        self._drag_px += abs(delta.x()) + abs(delta.y())

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

        if self.camera is not None and self._camera_mode is CameraMode.LOOK_AT:
            if ev.buttons() & Qt.MouseButton.LeftButton:
                self.camera.orbit(delta.x(), delta.y())
            elif ev.buttons() & Qt.MouseButton.MiddleButton:
                self.camera.pan(delta.x(), delta.y())
            elif ev.buttons() & Qt.MouseButton.RightButton:
                self.camera.dolly(-delta.y())

            self.render()

    def wheelEvent(self, ev: QWheelEvent):
        if not self.has_scene or self.camera is None or self._camera_mode is not CameraMode.LOOK_AT:
            super().wheelEvent(ev)
            return

        # angleDelta().y() is in eighths of a degree; 120 == one notch on most mouses.
        scroll_notches = ev.angleDelta().y() / 120.0
        self.camera.dolly(scroll_notches * self._ZOOM_NOTCH_SENSITIVITY)
        self.render()

        ev.accept()

    def _mouse_lock_enter(self, ev: QMouseEvent):
        # INVARIANT: Camera cannot be null!
        assert self.camera is not None

        if self._mode_transition_timer.isActive():
            self.camera.finish_transition()
            self._cancel_camera_mode_transition()

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

        x, y = self._display_position(ev.position())
        self._mouse_picker.Pick(x, y, 0, self.renderer)

        actor = self._mouse_picker.GetActor()
        if actor is None:
            return False

        # NOTE(Adam): With the scene mesh added to the pick list,
        #       this will correctly return None when clicking on the mesh,
        #       therefore blocking glyph selections through the mesh.
        camera_id = self.glyphs.camera_id_of_actor(actor)
        if camera_id is None:
            return False

        print(f"Selected camera: {camera_id}")
        self.camera_picked.emit(camera_id)

        return True

    def _display_position(self, position: QPointF) -> tuple[int, int]:
        """A Qt widget position as the render window's own pixel coordinates."""
        # NOTE(Adam): Qt uses the top-left origin.
        #             VTK uses OpenGL coordinates - bottom-left origin.
        dpr = self.devicePixelRatioF()  # Handle window DPI scaling
        x = int(position.x() * dpr)
        y = self.GetRenderWindow().GetSize()[1] - int(position.y() * dpr) - 1

        return x, y

    def _pick_target(self, position: QPointF) -> bool:
        """
        Select the surface target under the cursor.

        Emits `target_picked` with its row in the cloud, or `target_cleared`
        when the click landed on nothing. Returns whether a target was found.
        """
        index = self._target_under(position)

        if index is None:
            self.target_cleared.emit()
            return False

        self.target_picked.emit(index)

        return True

    def _target_under(self, position: QPointF) -> int | None:
        if self._targets is None or not len(self._targets):
            return None

        x, y = self._display_position(position)

        # The mesh goes first, so a click only ever reaches what it can see.
        self._surface_picker.Pick(x, y, 0, self.renderer)
        if self._surface_picker.GetActor() is not None:
            return self._within_reach(
                self._nearest_target(self._surface_picker.GetPickPosition()), x, y
            )

        # No mesh under the cursor: either it is hidden, or the click missed
        # the model. Either way the cloud is all that is left to hit.
        self._point_picker.Pick(x, y, 0, self.renderer)
        if self._point_picker.GetActor() is None:
            return None

        point_id = int(self._point_picker.GetPointId())
        if 0 <= point_id < len(self._targets):
            return self._within_reach(point_id, x, y)

        return self._within_reach(self._nearest_target(self._point_picker.GetPickPosition()), x, y)

    def _nearest_target(self, world_position) -> int:
        """The target closest to a point on the surface."""
        offsets = self._targets - np.asarray(world_position, dtype=np.float64)

        return int(np.argmin(np.einsum("ij,ij->i", offsets, offsets)))

    def _within_reach(self, index: int, x: int, y: int) -> int | None:
        """The target, unless the click landed too far away to have meant it.

        Picking off the surface hands back whichever target is nearest the
        point that was hit, and on bare mesh the nearest one can be metres
        off. Held to a radius around the cursor, a click on nothing stays
        nothing, and the selection is let go instead of jumping.
        """
        target_x, target_y = self._display_of_world(self._targets[index])
        reach = PICK_TARGET_RADIUS_PX * self.devicePixelRatioF()

        if float(np.hypot(target_x - x, target_y - y)) > reach:
            return None

        return index

    def _display_of_world(self, world_position) -> tuple[float, float]:
        """A point in the scene as the render window's own pixel coordinates."""
        self.renderer.SetWorldPoint(
            float(world_position[0]), float(world_position[1]), float(world_position[2]), 1.0
        )
        self.renderer.WorldToDisplay()
        display_x, display_y, _ = self.renderer.GetDisplayPoint()

        return display_x, display_y

    def _colour_observers(self, report: TargetReport, colour_by: str):
        """Give every camera that sees the target the colour of its own ray.

        The ray says which camera made a sector strong; wearing the same
        colour, the frustum out in the scene says where that camera is
        without the eye having to follow the line back.
        """
        top_camera = None if report.top_observer is None else report.top_observer.camera_index

        self.glyphs.set_observer_colours(
            {
                observer.camera_index: observer_colour(
                    observer, colour_by, self._weight_lut, top_camera
                )
                for observer in report.observers
            }
        )

    def toggle_glyph_wireframe(self, bool):
        """Toggle between the solid and wireframe representation for CameraGlyph.
        Render scene as soon as bool updates."""
        self.glyphs.wireframe_enabled = bool
        self.glyphs._refresh()
        self.render()

    # -- Window events ---------------------------------------------------

    def resizeEvent(self, ev):
        super().resizeEvent(ev)

        margin = 12
        self.camera_mode_gizmo.adjustSize()

        x = self.width() - self.camera_mode_gizmo.width() - margin
        y = margin

        self.camera_mode_gizmo.move(x, y)
        self.camera_mode_gizmo.raise_()

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
