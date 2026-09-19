from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import vtk
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

import viewscope_core as vc
from viewscope.config import ROUTE_SELECTED_COLOUR, ROUTE_UNSELECTED_COLOUR
from viewscope.scene import transform
from viewscope.scene.camera import CameraMode


class FloorGrid:
    """A grid in the floor that provides a reference for navigation within the scene.
    This is a 2.5D grid because the z-layer isn't used."""

    def __init__(self, renderer, grid_size=20, spawn_position=(0, 0, 0), scale: float = 1.0):
        self.grid_actor = None
        self.axes_actors = None
        self.structured_grid = None
        self.build(renderer, grid_size, spawn_position, scale)

    def build(self, renderer, grid_size: int, spawn_position: tuple, scale: float):
        """This creates the actors to be added to the renderer.
        The grid is a structured grid of points and the axes are lines."""
        self.spawn_position = tuple(spawn_position)
        self.structured_grid = self.create_structured_grid(grid_size)

        # - Mapper and Actor
        grid_mapper = vtk.vtkDataSetMapper()
        grid_mapper.SetInputData(self.structured_grid)

        self.grid_actor = vtk.vtkActor()
        self.grid_actor.SetMapper(grid_mapper)

        # - Grid actor Customization
        self.grid_actor.SetScale(scale, scale, scale)
        self.grid_actor.GetProperty().SetOpacity(0.1)
        self.grid_actor.GetProperty().SetRepresentationToWireframe()  # Set to grid-like appearance

        self.grid_actor.SetPosition(*spawn_position)  # Position the grid in the scene
        renderer.AddActor(self.grid_actor)

        # - Render two separate lines: x and y axes.
        offset_factor = 50  # Length of the axes lines

        x_actor = self.create_axes_line(
            (-offset_factor, 0, 0),  # Building line at its local origin.
            (offset_factor, 0, 0),
            (1.0, 0.0, 0.0),
        )  # Red line
        y_actor = self.create_axes_line(
            (0, -offset_factor, 0),
            (0, offset_factor, 0),
            (0.0, 1.0, 0.0),
        )  # Green line
        self.axes_actors = [x_actor, y_actor]
        for axis in self.axes_actors:
            axis.SetScale(scale, scale, scale)
            axis.SetPosition(*spawn_position)  # Place at spawn position last.

        renderer.AddActor(x_actor)
        renderer.AddActor(y_actor)

    def create_axes_line(self, start_point, end_point, color):
        """Creates a line actor between two points with custom color."""
        axis_line = vtk.vtkLineSource()
        axis_line.SetPoint1(start_point)
        axis_line.SetPoint2(end_point)
        axis_mapper = vtk.vtkPolyDataMapper()
        axis_mapper.SetInputConnection(axis_line.GetOutputPort())
        axis_actor = vtk.vtkActor()
        axis_actor.SetMapper(axis_mapper)
        axis_actor.GetProperty().SetColor(color)
        axis_actor.GetProperty().SetLineWidth(2.0)
        axis_actor.GetProperty().SetOpacity(0.75)

        return axis_actor

    def create_structured_grid(self, grid_size=8):
        """Create a structured square grid of points with a specified grid size.
        This is a 2.5D grid, as the Z-layer isn't used.
        The grid points are centered around the origin."""
        points = vtk.vtkPoints()
        half_size = (grid_size - 1) / 2.0  # center of the point lattice (suggested by DeepSeek)
        # Create grid of points
        for j in range(0, grid_size):
            for i in range(0, grid_size):
                points.InsertNextPoint(i - half_size, j - half_size, 0)

        structured_grid = vtk.vtkStructuredGrid()
        structured_grid.SetDimensions(grid_size, grid_size, 1)
        structured_grid.SetPoints(points)

        return structured_grid

    def move_to(self, spawn_position: tuple):
        """Re-anchor the grid, once a scene says where its ground actually is.

        Bundles do not share a coordinate frame: one survey sits hundreds of
        metres from the origin, the next straddles it."""
        self.spawn_position = tuple(float(v) for v in spawn_position)
        for actor in (self.grid_actor, *(self.axes_actors or [])):
            if actor is not None:
                actor.SetPosition(*self.spawn_position)

    def set_visible(self, visible: bool):
        if (self.grid_actor is not None) and (self.axes_actors is not None):
            self.grid_actor.SetVisibility(visible)
            self.axes_actors[0].SetVisibility(visible)
            self.axes_actors[1].SetVisibility(visible)

    def remove_from(self, renderer: vtk.vtkRenderer):
        if self.grid_actor is not None and self.axes_actors is not None:
            renderer.RemoveActor(self.grid_actor)
            self.grid_actor = None
            for actor in self.axes_actors:
                renderer.RemoveActor(actor)
            self.axes_actors = None


class CameraGlyphs:
    """One frustum per planned viewpoint."""

    # Camera Colours
    COLOUR_ACTIVE: tuple = (1.00, 0.85, 0.10)  # Gold
    COLOUR_NEW: tuple = (0.20, 0.80, 1.00)  # Cyan

    def __init__(self, plan: vc.Plan):
        self.glyphs: dict[vtk.vtkActor, int] = {}
        #: The plan id of every row, so a loaded file can name the viewpoints
        #: it wants drawn by id rather than by position in the plan.
        self.ids: tuple[str, ...] = tuple(plan.ids)
        for i in range(len(plan.positions)):
            vertices, faces, colours, edges = vc.camera_glyph(
                plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
            )
            actor = self._build(transform.glyph_polydata(vertices, faces, colours, edges))
            self.glyphs[actor] = i

        self._visible: bool = True
        self._active: int | None = None
        self._route: set[int] | None = None
        self._shown: set[str] | None = None
        #: The camera the user has selected, wearing COLOUR_ACTIVE.
        self._selected: int | None = None
        #: Camera index -> colour, for the observers of the picked target.
        self._observers: dict[int, tuple[float, float, float]] = {}
        self._outline: type = CameraOutline
        self.wireframe_enabled: bool = False

        self.new_ids: set[str] = set()  # Draw the new camera's in color: CYAN

    @property
    def actors(self) -> list[vtk.vtkActor]:
        return list(self.glyphs.keys())

    def add_to(self, renderer: vtk.vtkRenderer):
        for actor in self.glyphs:
            renderer.AddActor(actor)

    def remove_from(self, renderer: vtk.vtkRenderer):
        for actor in self.glyphs:
            renderer.RemoveActor(actor)

        self.glyphs.clear()

    def set_visible(self, visible: bool):
        self._visible = visible
        self._refresh()

    def set_active(self, index: int | None):
        """Track which frustum the viewer is sitting inside."""
        self._active = index
        self._refresh()

    def set_selected(self, index: int | None):
        """Mark the camera the user has picked; None when nothing is picked."""
        self._selected = index
        self._refresh()

    def set_observer_colours(self, colours: dict[int, tuple[float, float, float]] | None):
        """Paint the observers of the picked target; None when no target is up."""
        self._observers = dict(colours or {})
        self._refresh()

    def set_route(self, selected: set[int] | None, shown: set[str] | None = None):
        """Paint the route: blue for in, dimmed for out.

        Pass None to give every frustum its own colours back, which is what
        happens the moment route planning stops.

        `shown` is the plan ids a loaded file named. Every camera in the scene
        whose id is not one of them is switched off rather than dimmed, so the
        scene holds that plan and nothing else. None, the usual case, draws
        every viewpoint the plan has.
        """
        self._route = None if selected is None else set(selected)
        self._shown = None if shown is None else set(shown)
        self._refresh()

    def set_new_cameras(self, ids: set[str] | None):
        """Place the given IDs in the set for the new camera IDs"""
        if ids is None:
            self.new_ids = set()  # Empty set
            return
        self.new_ids = set(ids)

    def show_only(self, ids: set[str] | None):
        """Switch off every camera the given plan ids do not name."""
        self._shown = None if ids is None else set(ids)
        self._refresh()

    def camera_id_of_actor(self, actor: vtk.vtkActor) -> int | None:
        return self.glyphs.get(actor)

    def actor_of_id(self, camera_id: int) -> vtk.vtkActor | None:
        for actor, i in self.glyphs.items():
            if i == camera_id:
                return actor
        return None

    @staticmethod
    def _build(polydata: vtk.vtkPolyData):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetLineWidth(2.0)

        return actor

    def _refresh(self):
        for actor, id in self.glyphs.items():
            # Every camera in the scene, one at a time: it is drawn only if
            # the glyphs are on at all, it is not the frustum you are sitting
            # inside (that one fills the view), and, when a plan has been
            # loaded, that plan names its id.
            actor.SetVisibility(
                self._visible
                and id != self._active
                and (self._shown is None or self.ids[id] in self._shown)
            )

            # Wireframe vs Surface mode
            if id == self._selected or id in self._observers:
                self.set_frustrum_representation(actor, "Observer")
            else:
                self.set_frustrum_representation(actor, "none")

            mapper = actor.GetMapper()
            colour = self._colour_of(id)

            if colour is None:
                # The glyph carries its own vertex colours; let them through.
                mapper.ScalarVisibilityOn()
                actor.GetProperty().SetColor(1.0, 1.0, 1.0)
                continue

            mapper.ScalarVisibilityOff()
            actor.GetProperty().SetColor(*colour)

    def _colour_of(self, id: int) -> tuple[float, float, float] | None:
        """What one frustum wears, strongest claim first, or None for its own colours.

        Every colour a glyph can wear is decided here, from state, and applied
        by a full _refresh. Nothing paints a glyph on its own: a colour that is
        set directly is a colour nothing knows how to take off again, which is
        how a camera used to keep the selection gold after the selection had
        moved on.
        """
        if id == self._selected:
            return self.COLOUR_ACTIVE

        if id in self._observers:
            return self._observers[id]

        # if self.ids[id] in self.new_ids: # check if string ID is in new set
        #     return self.COLOUR_NEW

        if self._route is not None:
            return ROUTE_SELECTED_COLOUR if id in self._route else ROUTE_UNSELECTED_COLOUR

        if self.ids[id] in self.new_ids:  # check if string ID is in new set
            return self.COLOUR_NEW

        return None

    def set_frustrum_representation(self, actor: vtk.vtkActor, mode: str):
        """Set a frustrum's representation to surface or wireframe, based on their 'mode'.
        If that actor is an observer -> surface/filled representation.
        Otherwise, if not an observer -> wireframe representation"""
        if mode == "Observer":
            actor.GetProperty().SetRepresentationToSurface()
            actor.GetProperty().SetOpacity(1.0)
        else:
            actor.GetProperty().SetOpacity(0.2)  # change opacity regardless
            if self.wireframe_enabled:
                actor.GetProperty().SetRepresentationToWireframe()
            else:
                actor.GetProperty().SetRepresentationToSurface()


class CameraOutline:
    """The outline for a selected camera. Working with its position and not the camera itself."""

    def __init__(self):
        self.outline_actor = None

    def build(self, renderer: vtk.vtkRenderer, position: tuple[float, float, float]):
        """
        Spawn the outline at the position of the selected camera. This doesn't
        modify the camera glyph at all.
        """
        tempActor = vtk.vtkCubeSource()
        tempActor.SetCenter(position[0], position[1], position[2])
        tempActor.SetXLength(2)
        tempActor.SetYLength(2)
        tempActor.SetZLength(2)

        outlineFilter = vtk.vtkOutlineFilter()
        outlineFilter.SetInputConnection(tempActor.GetOutputPort())

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(outlineFilter.GetOutputPort())

        self.outline_actor = vtk.vtkActor()
        self.outline_actor.SetMapper(mapper)
        colors = vtk.vtkNamedColors()  # Need to create instance first, before getting color
        self.outline_actor.GetProperty().SetColor(colors.GetColor3d("Gold"))
        self.outline_actor.GetProperty().SetLineWidth(4.0)

        renderer.AddActor(self.outline_actor)

    def remove_from(self, renderer: vtk.vtkRenderer):
        if self.outline_actor is not None:
            renderer.RemoveActor(self.outline_actor)
            self.outline_actor = None


class CameraModeGizmo(QFrame):
    """Small floating control for switching camera interaction modes."""

    mode_changed = Signal(CameraMode)

    # The frame is sized from these rather than from sizeHint(). main.py sets
    # an application-wide stylesheet, which switches Qt to QStyleSheetStyle,
    # and under it the layout's QWidgetItems report each button 12px shorter
    # than the button's own sizeHint(). The frame's hint comes out ~22px short,
    # Viewport.resizeEvent's adjustSize() shrinks it to that, and the layout
    # then crams both buttons into less room than they need - they overlap.
    BUTTON_HEIGHT = 24
    BUTTON_GAP = 6
    FRAME_PADDING = 8
    FRAME_BORDER = 1  # Matches the 1px border in the stylesheet below.

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("CameraModeGizmo")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._buttons: dict[CameraMode, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self.FRAME_PADDING, self.FRAME_PADDING, self.FRAME_PADDING, self.FRAME_PADDING
        )

        # Spacing is an explicit spacer item, not layout spacing: with the
        # item hints under-reported, the layout drops its own spacing when it
        # is short on room and leaves the buttons edge to edge.
        layout.setSpacing(0)

        self._add_mode(
            layout,
            CameraMode.TRACKBALL,
            "🖱",
            "Trackball Camera",
        )

        layout.addSpacing(self.BUTTON_GAP)

        self._add_mode(
            layout,
            CameraMode.LOOK_AT,
            "✦",
            "Look-At Camera",
        )

        self.setStyleSheet("""
            #CameraModeGizmo {
                background: rgba(25, 25, 28, 220);
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 7px;
            }

            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 180);
                border: none;
                border-radius: 5px;
                padding: 5px 9px;
                text-align: left;
                font-size: 11px;
            }

            QPushButton:hover {
                background: rgba(255, 255, 255, 20);
                color: white;
            }

            QPushButton:checked {
                background: rgba(80, 140, 255, 100);
                color: white;
            }
        """)

        self._apply_fixed_size()
        self.set_mode(CameraMode.LOOK_AT)

    def _apply_fixed_size(self):
        """
        Pin the frame to what the buttons actually need, so a stylesheet-skewed
        sizeHint can never squeeze them. See the note on BUTTON_HEIGHT.
        """
        count = len(self._buttons)
        chrome = 2 * (self.FRAME_PADDING + self.FRAME_BORDER)

        widest = max(button.sizeHint().width() for button in self._buttons.values())
        height = self.BUTTON_HEIGHT * count + self.BUTTON_GAP * (count - 1)

        self.setFixedSize(chrome + widest, chrome + height)

    def _add_mode(self, layout: QVBoxLayout, mode: CameraMode, icon: str, text: str):
        button = QPushButton(f"{icon}  {text}", self)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(self.BUTTON_HEIGHT)

        button.clicked.connect(lambda checked=False, m=mode: self.set_mode(m))

        self._buttons[mode] = button
        layout.addWidget(button)

    def set_mode(self, mode: CameraMode):
        if mode not in self._buttons:
            return

        for button_mode, button in self._buttons.items():
            button.setChecked(button_mode == mode)

        self.mode_changed.emit(mode)

    def set_current_mode(self, mode: CameraMode):
        """Update the visual state without emitting mode_changed."""
        for button_mode, button in self._buttons.items():
            button.setChecked(button_mode == mode)


class AxisHandleWidget:
    """Three translate arrows (X/Y/Z) plus two rotate rings (yaw/pitch).

    Translation: one arrow per world axis, dragged along its own axis by
    intersecting the mouse ray with the plane that contains that axis and
    best faces the camera.

    Rotation: two rings, not three - by design, not an oversight.
      - "yaw":   a ring lying flat in the world XY plane, rotating about
                 world Z (the vertical axis). Unambiguous regardless of
                 where the camera is facing.
      - "pitch": a ring standing in the vertical plane that contains the
                 camera's current forward direction, rotating about the
                 horizontal axis perpendicular to that heading.

    Claude was used to generate this class, the building of handles,
    the picker and draggging logic, and handling translations.
    Wiring this into viewport.py and window.py, was done manually
    """

    _AXES: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
        "x": ((1.0, 0.0, 0.0), (0.85, 0.20, 0.20)),
        "y": ((0.0, 1.0, 0.0), (0.20, 0.85, 0.20)),
        "z": ((0.0, 0.0, 1.0), (0.20, 0.45, 0.90)),
    }

    _RING_COLOURS: dict[str, tuple[float, float, float]] = {
        "yaw": (0.95, 0.85, 0.20),
        "pitch": (0.85, 0.35, 0.85),
    }

    def __init__(self, renderer: vtk.vtkRenderer):
        self.renderer = renderer

        self.picker = vtk.vtkCellPicker()
        self.picker.SetTolerance(0.0)
        self.picker.PickFromListOn()

        self._axis_of: dict[vtk.vtkActor, np.ndarray] = {}
        self._rotation_axis_of: dict[vtk.vtkActor, tuple[str, np.ndarray]] = {}
        self._actors: list[vtk.vtkActor] = []
        self._target: vtk.vtkActor | None = None

        self._heading_deg = 0.0

        self._on_move: Callable[[np.ndarray], None] | None = None
        self._on_rotate: Callable[[str, float], None] | None = None

        self._build_translate_handles()
        self._build_rotate_handles()

        self.active: bool = False

        # -- translate drag state --
        self._drag_axis = np.zeros(3)
        self._drag_plane_origin = np.zeros(3)
        self._drag_plane_normal = np.zeros(3)
        self._drag_last_t = 0.0

        # -- rotate drag state --
        self._rotate_axis = np.zeros(3)
        self._rotate_kind: str | None = None
        self._rotate_origin = np.zeros(3)
        self._rotate_plane_u = np.zeros(3)
        self._rotate_plane_v = np.zeros(3)
        self._rotate_last_angle = 0.0

        self.set_visible(False)

    # -- construction: translate arrows ---------------------------------

    def _build_translate_handles(self):
        for direction, colour in self._AXES.values():
            arrow = vtk.vtkArrowSource()
            arrow.SetTipResolution(16)
            arrow.SetShaftResolution(16)
            arrow.SetShaftRadius(0.01)
            arrow.SetTipRadius(0.03)
            arrow.SetTipLength(0.25)

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(arrow.GetOutputPort())

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*colour)
            actor.GetProperty().SetLighting(False)

            self._axis_of[actor] = np.array(direction, dtype=np.float64)
            self._actors.append(actor)
            self.renderer.AddActor(actor)
            self.picker.AddPickList(actor)

    # -- construction: rotate rings --------------------------------------

    def _build_rotate_handles(self):
        for kind in ("yaw", "pitch"):
            circle = vtk.vtkRegularPolygonSource()
            circle.SetNumberOfSides(48)
            circle.GeneratePolygonOff()
            circle.SetRadius(1.0)

            tube = vtk.vtkTubeFilter()
            tube.SetInputConnection(circle.GetOutputPort())
            tube.SetNumberOfSides(12)
            tube.SetRadius(0.015)

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(tube.GetOutputPort())

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*self._RING_COLOURS[kind])
            actor.GetProperty().SetLighting(False)

            self._rotation_axis_of[actor] = (kind, np.zeros(3))
            self._actors.append(actor)
            self.renderer.AddActor(actor)
            self.picker.AddPickList(actor)

    # -- attach / detach -------------------------------------------------

    def attach(
        self,
        actor: vtk.vtkActor,
        *,
        heading_deg: float = 0.0,
        on_move: Callable[[np.ndarray], None] | None = None,
        on_rotate: Callable[[str, float], None] | None = None,
    ):
        """Point the gizmo at an actor: place the handles at its centre, sized
        to it, and orient the pitch ring for its current heading.

        `on_move(new_centre)` is called with the target's new world-space
        centre after each translate drag tick.

        `on_rotate(axis, delta_deg)` is called with axis="yaw" or "pitch"
        and the incremental change in degrees after each rotate drag tick.
        """
        self._target = actor
        self._heading_deg = heading_deg
        self._on_move = on_move
        self._on_rotate = on_rotate
        self._place_handles()
        self.set_visible(True)

    def detach(self):
        self._target = None
        self._on_move = None
        self._on_rotate = None
        self.set_visible(False)

    def refresh(self, *, heading_deg: float | None = None):
        """Re-place the handles after something else has moved/turned the target."""
        if heading_deg is not None:
            self._heading_deg = heading_deg
        if self._target is not None:
            self._place_handles()

    def set_visible(self, visible: bool):
        for actor in self._actors:
            actor.SetVisibility(visible)

    def remove_from(self, renderer: vtk.vtkRenderer):
        for actor in self._actors:
            renderer.RemoveActor(actor)

    def _place_handles(self):
        assert self._target is not None

        bounds = self._target.GetBounds()
        centre = np.array(
            [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]
        )
        diag = math.sqrt(
            (bounds[1] - bounds[0]) ** 2
            + (bounds[3] - bounds[2]) ** 2
            + (bounds[5] - bounds[4]) ** 2
        )
        length = max(diag, 1e-3)

        for actor, direction in self._axis_of.items():
            actor.SetUserTransform(self._arrow_transform(centre, direction, length))

        right = self._horizontal_right_axis(self._heading_deg)
        world_up = np.array([0.0, 0.0, 1.0])

        for actor, (kind, _old_axis) in list(self._rotation_axis_of.items()):
            axis = world_up if kind == "yaw" else right
            self._rotation_axis_of[actor] = (kind, axis)
            actor.SetUserTransform(
                self._ring_transform(centre, np.array([0.0, 0.0, 1.0]), axis, length * 1.3)
            )

    @staticmethod
    def _arrow_transform(
        centre: np.ndarray, direction: np.ndarray, length: float
    ) -> vtk.vtkTransform:
        """vtkArrowSource points along +X by default; rotate it onto `direction`."""
        transform = vtk.vtkTransform()
        transform.Translate(*centre)
        transform.Concatenate(AxisHandleWidget._align_matrix(np.array([1.0, 0.0, 0.0]), direction))
        transform.Scale(length, length, length)
        return transform

    @staticmethod
    def _ring_transform(
        centre: np.ndarray, ring_normal: np.ndarray, target_normal: np.ndarray, radius: float
    ) -> vtk.vtkTransform:
        transform = vtk.vtkTransform()
        transform.Translate(*centre)
        transform.Concatenate(AxisHandleWidget._align_matrix(ring_normal, target_normal))
        transform.Scale(radius, radius, radius)
        return transform

    @staticmethod
    def _align_matrix(from_axis: np.ndarray, to_axis: np.ndarray) -> vtk.vtkMatrix4x4:
        """A pure-rotation matrix taking `from_axis` onto `to_axis`."""
        from_axis = from_axis / np.linalg.norm(from_axis)
        to_axis = to_axis / np.linalg.norm(to_axis)

        dot = float(np.clip(np.dot(from_axis, to_axis), -1.0, 1.0))
        rotation = vtk.vtkTransform()

        if dot < -0.9999:
            perp = np.cross(from_axis, [1.0, 0.0, 0.0])
            if np.linalg.norm(perp) < 1e-6:
                perp = np.cross(from_axis, [0.0, 1.0, 0.0])
            perp /= np.linalg.norm(perp)
            rotation.RotateWXYZ(180.0, *perp)
        elif dot < 0.9999:
            rot_axis = np.cross(from_axis, to_axis)
            rot_axis /= np.linalg.norm(rot_axis)
            rotation.RotateWXYZ(math.degrees(math.acos(dot)), *rot_axis)

        return rotation.GetMatrix()

    @staticmethod
    def _horizontal_right_axis(heading_deg: float) -> np.ndarray:
        """World-space horizontal axis to pitch about, for a camera facing
        `heading_deg`. Assumes yaw_deg=0 faces world +Y, increasing yaw
        rotates clockwise viewed from above (toward +X)."""
        theta = math.radians(heading_deg)
        forward = np.array([math.sin(theta), math.cos(theta), 0.0])
        return np.array([forward[1], -forward[0], 0.0])

    # -- dragging ---------------------------------------------------------

    def try_start_drag(self, x: int, y: int) -> bool:
        """Pick a handle under (x, y). Returns whether a drag started."""
        if self._target is None:
            return False

        self.picker.Pick(x, y, 0, self.renderer)
        actor = self.picker.GetActor()

        if actor in self._axis_of:
            return self._try_start_translate(actor, x, y)
        if actor in self._rotation_axis_of:
            return self._try_start_rotate(actor, x, y)
        return False

    def _try_start_translate(self, actor: vtk.vtkActor, x: int, y: int) -> bool:
        axis_world = self._axis_of[actor]
        origin = self._target_centre()

        plane = self._camera_facing_plane(axis_world, origin)
        if plane is None:
            return False
        normal, _view_dir = plane

        self._drag_axis = axis_world
        self._drag_plane_origin = origin
        self._drag_plane_normal = normal

        point = self._ray_plane_point(normal, origin, x, y)
        if point is None:
            return False

        self._drag_last_t = float(np.dot(point - origin, axis_world))
        self._rotate_kind = None
        self.active = True
        return True

    def _try_start_rotate(self, actor: vtk.vtkActor, x: int, y: int) -> bool:
        kind, axis_world = self._rotation_axis_of[actor]
        origin = self._target_centre()

        point = self._ray_plane_point(axis_world, origin, x, y)
        if point is None:
            return False

        u, v = self._in_plane_basis(axis_world)

        self._rotate_axis = axis_world
        self._rotate_kind = kind
        self._rotate_origin = origin
        self._rotate_plane_u = u
        self._rotate_plane_v = v

        offset = point - origin
        self._rotate_last_angle = math.atan2(np.dot(offset, v), np.dot(offset, u))
        self.active = True
        return True

    def drag(self, x: int, y: int):
        if not self.active or self._target is None:
            return

        if self._rotate_kind is not None:
            self._drag_rotate(x, y)
        else:
            self._drag_translate(x, y)

    def _drag_translate(self, x: int, y: int):
        point = self._ray_plane_point(self._drag_plane_normal, self._drag_plane_origin, x, y)
        if point is None:
            return

        t = float(np.dot(point - self._drag_plane_origin, self._drag_axis))
        delta = (t - self._drag_last_t) * self._drag_axis
        self._drag_last_t = t

        self._translate_target(delta)
        self._place_handles()

        if self._on_move is not None:
            self._on_move(self._target_centre())

    def _drag_rotate(self, x: int, y: int):
        point = self._ray_plane_point(self._rotate_axis, self._rotate_origin, x, y)
        if point is None:
            return

        offset = point - self._rotate_origin
        angle = math.atan2(
            np.dot(offset, self._rotate_plane_v), np.dot(offset, self._rotate_plane_u)
        )

        delta_angle = angle - self._rotate_last_angle
        delta_angle = (delta_angle + math.pi) % (2 * math.pi) - math.pi
        self._rotate_last_angle = angle

        delta_deg = math.degrees(delta_angle)

        self._rotate_target(self._rotate_axis, self._rotate_origin, delta_deg)
        self._place_handles()

        if self._on_rotate is not None and self._rotate_kind is not None:
            self._on_rotate(self._rotate_kind, delta_deg)

    def end_drag(self):
        self.active = False
        self._rotate_kind = None

    # -- shared geometry helpers ------------------------------------------

    def _target_centre(self) -> np.ndarray:
        assert self._target is not None
        bounds = self._target.GetBounds()
        return np.array(
            [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2]
        )

    def _camera_facing_plane(
        self, axis_world: np.ndarray, origin: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray] | None:
        camera = self.renderer.GetActiveCamera()
        view_vec = np.array(camera.GetPosition()) - origin
        view_dist = np.linalg.norm(view_vec)
        if view_dist < 1e-6:
            return None
        view_dir = view_vec / view_dist

        if abs(np.dot(axis_world, view_dir)) > 0.97:
            return None

        normal = np.cross(np.cross(axis_world, view_vec), axis_world)
        normal_len = np.linalg.norm(normal)
        if normal_len < 1e-6:
            return None

        return normal / normal_len, view_dir

    @staticmethod
    def _in_plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Two orthonormal vectors spanning the plane perpendicular to `normal`."""
        reference = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(normal, reference)) > 0.95:
            reference = np.array([1.0, 0.0, 0.0])

        u = np.cross(normal, reference)
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
        return u, v

    def _ray_plane_point(
        self, normal: np.ndarray, origin: np.ndarray, x: int, y: int
    ) -> np.ndarray | None:
        """Where the mouse ray crosses a plane, as a world-space point."""
        self.renderer.SetDisplayPoint(x, y, 0.0)
        self.renderer.DisplayToWorld()
        near = np.array(self.renderer.GetWorldPoint())
        near = near[:3] / near[3]

        self.renderer.SetDisplayPoint(x, y, 1.0)
        self.renderer.DisplayToWorld()
        far = np.array(self.renderer.GetWorldPoint())
        far = far[:3] / far[3]

        intersection = [0.0, 0.0, 0.0]
        t_line = vtk.reference(0.0)
        hit = vtk.vtkPlane.IntersectWithLine(
            near.tolist(),
            far.tolist(),
            normal.tolist(),
            origin.tolist(),
            t_line,  # type: ignore[ty:invalid-argument-type]
            intersection,
        )
        if not hit:
            return None

        return np.array(intersection)

    def _translate_target(self, delta: np.ndarray):
        """Apply a world-space translation on top of whatever transform is
        already there."""
        assert self._target is not None

        matrix = vtk.vtkMatrix4x4()
        existing = self._target.GetUserTransform()
        if existing is not None:
            matrix.DeepCopy(existing.GetMatrix())

        for i in range(3):
            matrix.SetElement(i, 3, matrix.GetElement(i, 3) + delta[i])

        transform = vtk.vtkTransform()
        transform.SetMatrix(matrix)
        self._target.SetUserTransform(transform)

    def _rotate_target(self, axis_world: np.ndarray, origin_world: np.ndarray, delta_deg: float):
        """Rotate the target by `delta_deg` about `axis_world`, pivoting at
        `origin_world`, on top of whatever transform is already there."""
        assert self._target is not None

        delta = vtk.vtkTransform()
        delta.Translate(*origin_world)
        delta.RotateWXYZ(delta_deg, *axis_world)
        delta.Translate(*(-origin_world))
        delta_matrix = delta.GetMatrix()

        existing = vtk.vtkMatrix4x4()
        current = self._target.GetUserTransform()
        if current is not None:
            existing.DeepCopy(current.GetMatrix())

        result = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Multiply4x4(delta_matrix, existing, result)

        transform = vtk.vtkTransform()
        transform.SetMatrix(result)
        self._target.SetUserTransform(transform)
