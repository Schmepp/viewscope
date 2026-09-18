from __future__ import annotations

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
        # self.new_camera_id = None
        self.wireframe_enabled: bool = True

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

    def show_only(self, ids: set[str] | None):
        """Switch off every camera the given plan ids do not name."""
        self._shown = None if ids is None else set(ids)
        self._refresh()

    def camera_id_of_actor(self, actor: vtk.vtkActor) -> int | None:
        return self.glyphs.get(actor)

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

        if self._route is not None:
            return ROUTE_SELECTED_COLOUR if id in self._route else ROUTE_UNSELECTED_COLOUR

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
