# NOTE(Adam): My question here is... What the fuck?

"""
The full-resolution textured model the camera view takes its photos from.
The main viewport draws the simplified scene.obj, because that is the half of
the application that has to stay interactive on a laptop without much GPU. A
simulated photograph is worth looking at only for the detail in it, so the
camera view draws the model the bundle was built from instead.
Reading it is a file job, not a drawing one: VTK parses the OBJ and decodes
the textures here, on a worker thread, and the interface thread only ever
receives finished actors.
"""

from __future__ import annotations

from pathlib import Path

import vtk
from PySide6.QtCore import QThread, Signal
from vtkmodules.vtkIOImport import vtkOBJImporter

from viewscope.config import GEOMETRY_COLOUR, PHOTO_MESH_DIR


def find_photo_mesh(data_dir) -> Path | None:
    """The full-resolution OBJ a bundle ships, or None when it ships none.
    Bundles are not required to carry one. Without it the camera view keeps
    the simplified mesh every other panel draws, which is the picture it has
    always shown.
    """
    if data_dir is None:
        return None

    folder = Path(data_dir) / PHOTO_MESH_DIR
    if not folder.is_dir():
        return None

    meshes = sorted(folder.glob("*.obj"))

    return meshes[0] if meshes else None


def find_materials(mesh_path: Path) -> Path | None:
    """The .mtl beside a model, by name where it matches and by folder where not.
    The name in the OBJ's own `mtllib` line would be authoritative, but it is
    written after the last vertex: on a model this size, finding it means
    reading the better part of a gigabyte to learn something the folder
    already says.
    """
    named = mesh_path.with_suffix(".mtl")
    if named.exists():
        return named

    materials = sorted(mesh_path.parent.glob("*.mtl"))

    return materials[0] if materials else None


class PhotoMesh:
    """
    The imported model, wearing the same face as MeshView.
    One actor per material, because the texture arrives as a set of tiles and
    an actor carries one texture at a time.
    """

    def __init__(self, actors, source=None):
        self.actors = list(actors)
        # What each actor was imported wearing, so geometry mode can put the
        # textures back afterwards.
        self._textures = [(actor, actor.GetTexture()) for actor in self.actors]
        # The render window the importer filled. Held only so it outlives the
        # import; nothing draws into it.
        self._source = source

    @property
    def cells(self) -> int:
        """How many triangles came in, for the status line."""
        return sum(actor.GetMapper().GetInput().GetNumberOfCells() for actor in self.actors)

    def add_to(self, renderer: vtk.vtkRenderer):
        for actor in self.actors:
            renderer.AddActor(actor)

    def remove_from(self, renderer: vtk.vtkRenderer):
        for actor in self.actors:
            renderer.RemoveActor(actor)

    def set_visible(self, visible: bool):
        for actor in self.actors:
            actor.SetVisibility(visible)

    def clone(self) -> PhotoMesh:
        """A second set of actors over the same triangles and the same images.
        Two renderers cannot share one set of actors: hiding the mesh in one
        panel would hide it in the other, and each render window uploads to
        its own GL context regardless. What is worth sharing is what was
        expensive to produce - the parsed geometry and the decoded textures -
        and both are held here by reference rather than copied.
        """
        actors = []
        for source, texture in self._textures:
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(source.GetMapper().GetInput())

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)

            if texture is not None:
                shared = vtk.vtkTexture()
                shared.SetInputData(texture.GetInput())
                # Sampled exactly as the original is, so the two panels draw
                # the same picture rather than one subtly softer than the other.
                shared.SetInterpolate(texture.GetInterpolate())
                shared.SetMipmap(texture.GetMipmap())
                shared.SetRepeat(texture.GetRepeat())
                shared.SetEdgeClamp(texture.GetEdgeClamp())
                shared.SetMaximumAnisotropicFiltering(texture.GetMaximumAnisotropicFiltering())
                actor.SetTexture(shared)

            actors.append(actor)

        return PhotoMesh(actors, self._source)

    def show_textured(self):
        """The model as it was photographed, with no shading of ours on top.
        These textures are the survey photographs themselves: the light in
        them was real light, already in the picture. Lighting them a second
        time is what blew the panel out, and there is nothing to recover
        once a texel has been driven past white. Ambient alone, at full
        strength, hands each one to the screen as it was captured.
        """
        for actor, texture in self._textures:
            if texture is not None:
                actor.SetTexture(texture)

            prop = actor.GetProperty()
            actor.GetMapper().ScalarVisibilityOn()
            prop.SetRepresentationToSurface()
            prop.SetAmbient(1.0)
            prop.SetAmbientColor(1.0, 1.0, 1.0)
            prop.SetDiffuse(0.0)
            prop.SetSpecular(0.0)
            prop.EdgeVisibilityOff()

    def show_geometry(self):
        """The shape on its own, textures off.
        No wireframe over it, unlike the simplified mesh: seven million
        triangles of edge are a solid block of colour and cost a second a
        frame to draw.
        """
        for actor in self.actors:
            prop = actor.GetProperty()
            actor.SetTexture(None)
            actor.GetMapper().ScalarVisibilityOff()
            prop.SetRepresentationToSurface()
            # Lit the usual way here, unlike the textured mode: with the
            # photographs off there is no baked light left, and shading is
            # the only thing giving the shape any relief.
            prop.SetAmbient(0.0)
            prop.SetDiffuse(1.0)
            prop.SetSpecular(0.0)
            prop.SetColor(*GEOMETRY_COLOUR)
            prop.EdgeVisibilityOff()


class PhotoMeshLoader(QThread):
    """Reads the full-resolution model off the interface thread.
    vtkOBJImporter is what makes this worth doing at all: it reads the
    gigabyte OBJ, its materials and its textures in a handful of seconds,
    where the trimesh path the planning library uses takes minutes.
    """

    #: A finished PhotoMesh, ready to be added to a renderer.
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)

        # Built here on the interface thread, and only filled by run(). The
        # importer wants a render window to hang its actors on, and a render
        # window is not a thing to construct off the main thread; this one is
        # offscreen and never drawn either way.
        self._renderer = vtk.vtkRenderer()
        self._window = vtk.vtkRenderWindow()
        self._window.SetOffScreenRendering(1)
        self._window.AddRenderer(self._renderer)

    def run(self):
        try:
            self.loaded.emit(self._read())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _read(self) -> PhotoMesh:
        importer = vtkOBJImporter()
        importer.SetFileName(str(self.path))
        importer.SetRenderWindow(self._window)

        materials = find_materials(self.path)
        if materials is not None:
            importer.SetFileNameMTL(str(materials))
            importer.SetTexturePath(str(self.path.parent))

        importer.Update()

        actors = self._imported_actors()
        if not actors:
            raise ValueError(f"{self.path.name} imported no geometry")

        for actor in actors:
            # Parse the geometry and decode the textures here rather than
            # leaving them for the first frame, which the interface thread
            # draws. What is left for it is the upload to the GPU.
            actor.GetMapper().Update()
            texture = actor.GetTexture()
            if texture is not None:
                texture.Update()
                # The importer leaves sampling on nearest. Up close a single
                # texel covers many pixels, and without this the photograph
                # comes apart into squares.
                texture.InterpolateOn()

            self._renderer.RemoveActor(actor)

        return PhotoMesh(actors, self._window)

    def _imported_actors(self) -> list:
        """Every actor the importer made, minus the empty ones.
        A material the model declares but never uses still arrives as an
        actor, holding no triangles.
        """
        collection = self._renderer.GetActors()
        collection.InitTraversal()

        actors = []
        for _ in range(collection.GetNumberOfItems()):
            actor = collection.GetNextActor()
            mapper = actor.GetMapper()
            if mapper is None:
                continue

            mapper.Update()
            if mapper.GetInput().GetNumberOfCells():
                actors.append(actor)

        return actors
