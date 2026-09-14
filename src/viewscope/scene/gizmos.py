from __future__ import annotations

import vtk

import viewscope_core as vc
from viewscope.scene import transform


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

    def __init__(self, plan: vc.Plan):
        self.glyphs: dict[vtk.vtkActor, int] = {}
        for i in range(len(plan.positions)):
            vertices, faces, colours, edges = vc.camera_glyph(
                plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
            )
            actor = self._build(transform.glyph_polydata(vertices, faces, colours, edges))
            self.glyphs[actor] = i

        self._visible: bool = True
        self._active: int | None = None
        self._outline: type = CameraOutline

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
            # Never draw the frustum you are inside; it fills the view.
            actor.SetVisibility(self._visible and id != self._active)


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
