"""
One class per thing drawn in the viewport.

Each view owns its actors and the state needed to restyle them. None of them
know about Qt, panels or each other -- the viewport wires them together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
import vtk
from vtkmodules.util import numpy_support as vtknp

import viewscope_core as vc
from viewscope import transform
from viewscope.config import EDGE_COLOUR, GEOMETRY_COLOUR, OCCLUDED_COLOUR, VISIBLE_COLOUR


@dataclass(frozen=True)
class FieldStats:
    """Summary of the scalar field currently colouring the cloud."""

    field: str
    minimum: float
    mean: float
    maximum: float


class MeshView:
    """The scene mesh, shown either textured or as plain geometry."""

    def __init__(self, mesh: trimesh.Geometry):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(transform.trimesh_to_polydata(mesh))

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)

        self.texture = transform.texture_from_mesh(mesh)
        if self.texture is not None:
            self.actor.SetTexture(self.texture)

    def add_to(self, renderer: vtk.vtkRenderer):
        renderer.AddActor(self.actor)

    def remove_from(self, renderer: vtk.vtkRenderer):
        renderer.RemoveActor(self.actor)

    def set_visible(self, visible: bool):
        self.actor.SetVisibility(visible)

    def show_textured(self):
        prop = self.actor.GetProperty()

        if self.texture:
            self.actor.SetTexture(self.texture)

        self.actor.GetMapper().ScalarVisibilityOn()
        prop.SetRepresentationToSurface()
        prop.SetColor(1.0, 1.0, 1.0)
        prop.EdgeVisibilityOff()

    def show_geometry(self):
        prop = self.actor.GetProperty()
        # self.actor.SetTexture(None)
        self.actor.GetMapper().ScalarVisibilityOff()
        prop.SetRepresentationToSurface()
        prop.SetColor(*GEOMETRY_COLOUR)
        prop.EdgeVisibilityOn()
        prop.SetEdgeColor(*EDGE_COLOUR)
        prop.SetLineWidth(1.0)


class TargetCloudView:
    """Score-coloured target points, plus the scalar bar that explains them."""

    def __init__(self, targets: np.ndarray, scores: object | None = None, point_size: float = 2.0):
        self.scores = scores
        self.polydata = transform.cloud_polydata(targets)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(self.polydata)

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)
        self.actor.GetProperty().SetPointSize(point_size)
        mapper.SetColorModeToMapScalars()

        self.lut = None
        self.scalar_bar = None
        self._field = None
        self._occluding = False
        self._occlusion_lut = self._build_occlusion_lut()
        if scores is not None:
            self.lut = vtk.vtkLookupTable()
            self.lut.SetHueRange(0.667, 0.0)  # blue low, red high
            self.lut.Build()
            mapper.SetLookupTable(self.lut)

            self.scalar_bar = vtk.vtkScalarBarActor()
            self.scalar_bar.SetLookupTable(self.lut)
            self.scalar_bar.SetNumberOfLabels(5)
            self.scalar_bar.SetWidth(0.055)
            self.scalar_bar.SetHeight(0.32)
            self.scalar_bar.SetPosition(0.93, 0.58)

    @property
    def has_scores(self) -> bool:
        return self.scores is not None

    def add_to(self, renderer: vtk.vtkRenderer):
        renderer.AddActor(self.actor)
        if self.scalar_bar is not None:
            renderer.AddActor2D(self.scalar_bar)

    def remove_from(self, renderer: vtk.vtkRenderer):
        renderer.RemoveActor(self.actor)
        if self.scalar_bar is not None:
            renderer.RemoveActor2D(self.scalar_bar)

    def set_visible(self, visible: bool):
        self.actor.SetVisibility(visible)
        if self.scalar_bar is not None:
            self.scalar_bar.SetVisibility(visible and not self._occluding)

    def set_point_size(self, size: float):
        self.actor.GetProperty().SetPointSize(float(size))

    def set_field(self, field: str):
        """Colour by one scalar field. Returns its stats, or None if unscored."""
        if self.scores is None:
            return None

        self._field = field
        values = np.ascontiguousarray(getattr(self.scores, field), dtype=np.float32)

        if self.scalar_bar is not None:
            self.scalar_bar.SetTitle(field)

        # Occlusion colouring owns the scalars while it is on; remember the
        # field so switching back picks up the one the panel is showing.
        if not self.occluding:
            array = vtknp.numpy_to_vtk(values, deep=True)
            array.SetName(field)
            self.polydata.GetPointData().SetScalars(array)

            mapper = self.actor.GetMapper()
            mapper.SetScalarRange(float(values.min()), float(values.max()))
            mapper.ScalarVisibilityOn()

        return FieldStats(field, float(values.min()), float(values.mean()), float(values.max()))

    @property
    def occluding(self) -> bool:
        return self._occluding

    def set_occlusion(self, mask: np.ndarray | None):
        """
        Colour points red where the selected camera can see them, grey elsewhere.

        Pass None to go back to the scalar field colouring.
        """
        self._occluding = mask is not None
        mapper = self.actor.GetMapper()

        if mask is None:
            if self.scalar_bar is not None:
                self.scalar_bar.SetVisibility(self.actor.GetVisibility())
            if self.lut is not None:
                mapper.SetLookupTable(self.lut)
            if self._field is not None:
                self.set_field(self._field)
            else:
                mapper.ScalarVisibilityOff()
            return

        values = np.ascontiguousarray(mask, dtype=np.float32)
        array = vtknp.numpy_to_vtk(values, deep=True)
        array.SetName("visible")
        self.polydata.GetPointData().SetScalars(array)

        mapper.SetLookupTable(self._occlusion_lut)
        mapper.SetScalarRange(0.0, 1.0)
        mapper.ScalarVisibilityOn()

        # The scalar bar explains the field, which is not what is on screen.
        if self.scalar_bar is not None:
            self.scalar_bar.SetVisibility(False)

    @staticmethod
    def _build_occlusion_lut():
        lut = vtk.vtkLookupTable()
        lut.SetNumberOfTableValues(2)
        lut.SetTableRange(0.0, 1.0)
        lut.SetTableValue(0, *OCCLUDED_COLOUR, 1.0)
        lut.SetTableValue(1, *VISIBLE_COLOUR, 1.0)
        lut.Build()
        return lut


class CameraGlyphs:
    """One frustum per planned viewpoint."""

    def __init__(self, plan: vc.Plan):
        self.actors = []
        for i in range(len(plan.positions)):
            vertices, faces, colours, edges = vc.camera_glyph(
                plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
            )
            self.actors.append(
                self._build(transform.glyph_polydata(vertices, faces, colours, edges))
            )

        self._visible = True
        self._active = None
        self._outline = CameraOutline

    def add_to(self, renderer: vtk.vtkRenderer):
        for actor in self.actors:
            renderer.AddActor(actor)

    def remove_from(self, renderer: vtk.vtkRenderer):
        for actor in self.actors:
            renderer.RemoveActor(actor)

        self.actors.clear()

    def set_visible(self, visible: bool):
        self._visible = visible
        self._refresh()

    def set_active(self, index: int | None):
        """Track which frustum the viewer is sitting inside."""
        self._active = index
        self._refresh()

    @staticmethod
    def _build(polydata: vtk.vtkPolyData):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetLineWidth(2.0)

        return actor

    def _refresh(self):
        for i, actor in enumerate(self.actors):
            # Never draw the frustum you are inside; it fills the view.
            actor.SetVisibility(self._visible and i != self._active)


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
        tempActor.SetCenter(position[0], position[1], position[2])  # set posotion
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
