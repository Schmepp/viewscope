"""One class per thing drawn in the viewport.

Each view owns its actors and the state needed to restyle them. None of them
know about Qt, panels or each other -- the viewport wires them together.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import vtk
from vtkmodules.util import numpy_support as vtknp

import viewscope_core as vc
from viewscope import transform
from viewscope.config import EDGE_COLOUR, GEOMETRY_COLOUR


@dataclass(frozen=True)
class FieldStats:
    """Summary of the scalar field currently colouring the cloud."""

    field: str
    minimum: float
    mean: float
    maximum: float


class MeshView:
    """The scene mesh, shown either textured or as plain geometry."""

    def __init__(self, mesh):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(transform.trimesh_to_polydata(mesh))

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)

        self.texture = transform.texture_from_mesh(mesh)
        if self.texture is not None:
            self.actor.SetTexture(self.texture)

    def add_to(self, renderer):
        renderer.AddActor(self.actor)

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

    def __init__(self, targets, scores=None, point_size: float = 2.0):
        self.scores = scores
        self.polydata = transform.cloud_polydata(targets)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(self.polydata)

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(mapper)
        self.actor.GetProperty().SetPointSize(point_size)

        self.lut = None
        self.scalar_bar = None
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

    def add_to(self, renderer):
        renderer.AddActor(self.actor)
        if self.scalar_bar is not None:
            renderer.AddActor2D(self.scalar_bar)

    def set_visible(self, visible: bool):
        self.actor.SetVisibility(visible)
        if self.scalar_bar is not None:
            self.scalar_bar.SetVisibility(visible)

    def set_point_size(self, size: float):
        self.actor.GetProperty().SetPointSize(float(size))

    def set_field(self, field: str):
        """Colour by one scalar field. Returns its stats, or None if unscored."""
        if self.scores is None:
            return None

        values = np.ascontiguousarray(getattr(self.scores, field), dtype=np.float32)
        array = vtknp.numpy_to_vtk(values, deep=True)
        array.SetName(field)
        self.polydata.GetPointData().SetScalars(array)

        mapper = self.actor.GetMapper()
        mapper.SetScalarRange(float(values.min()), float(values.max()))
        mapper.ScalarVisibilityOn()

        if self.scalar_bar is not None:
            self.scalar_bar.SetTitle(field)

        return FieldStats(
            field, float(values.min()), float(values.mean()), float(values.max())
        )


class CameraGlyphs:
    """One frustum per planned viewpoint."""

    def __init__(self, plan):
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

    @staticmethod
    def _build(polydata):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetLineWidth(2.0)
        return actor

    def add_to(self, renderer):
        for actor in self.actors:
            renderer.AddActor(actor)

    def set_visible(self, visible: bool):
        self._visible = visible
        self._refresh()

    def set_active(self, index):
        """Track which frustum the viewer is sitting inside."""
        self._active = index
        self._refresh()

    def _refresh(self):
        for i, actor in enumerate(self.actors):
            # Never draw the frustum you are inside; it fills the view.
            actor.SetVisibility(self._visible and i != self._active)
