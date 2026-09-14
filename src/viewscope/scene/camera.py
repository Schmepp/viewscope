from __future__ import annotations

import vtk

import viewscope_core as vc
from viewscope import transform


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
