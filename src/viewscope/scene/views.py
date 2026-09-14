from __future__ import annotations

import numpy as np
import trimesh
import vtk
from vtkmodules.util import numpy_support as vtknp

from viewscope.config import EDGE_COLOUR, GEOMETRY_COLOUR, OCCLUDED_COLOUR, VISIBLE_COLOUR
from viewscope.scene import transform
from viewscope.scene.stats import FieldStats


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

    @property
    def occluding(self) -> bool:
        return self._occluding

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
