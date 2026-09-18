# Unit tests for src/viewscope/scene/photo_mesh.py

import os

# Must be set before Qt picks a platform plugin, so these run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import vtk  # noqa: E402

from viewscope.scene import photo_mesh  # noqa: E402
from viewscope.scene.photo_mesh import PhotoMeshLoader  # noqa: E402

TEXTURE_DIM = 64
CAP = 16


def textured_actor(dim: int = TEXTURE_DIM) -> vtk.vtkActor:
    """An actor over real triangles, wearing a square texture of the given size."""
    sphere = vtk.vtkSphereSource()
    sphere.Update()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(sphere.GetOutput())

    image = vtk.vtkImageData()
    image.SetDimensions(dim, dim, 1)
    image.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 3)

    texture = vtk.vtkTexture()
    texture.SetInputData(image)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.SetTexture(texture)
    return actor


class FakeImporter:
    """Stands in for vtkOBJImporter, which wants a gigabyte of OBJ and a GL context."""

    actors: list[vtk.vtkActor] = []

    def SetFileName(self, name):
        pass

    def SetFileNameMTL(self, name):
        pass

    def SetTexturePath(self, path):
        pass

    def SetRenderWindow(self, window):
        self.window = window

    def Update(self):
        renderer = self.window.GetRenderers().GetFirstRenderer()
        for actor in FakeImporter.actors:
            renderer.AddActor(actor)


@pytest.fixture
def model(tmp_path):
    """A stand-in OBJ on disk, so the path handling around the read is real."""
    path = tmp_path / "model.obj"
    path.write_text("")
    return path


@pytest.fixture
def calls(monkeypatch):
    """Swap the importer and the disk cache out, and record what the read asked of them."""
    seen = {"read": 0, "written": []}

    monkeypatch.setattr(photo_mesh, "vtkOBJImporter", FakeImporter)

    def cached_actors(obj_path, mtl_path):
        seen["read"] += 1
        return None  # never a hit, so the read always goes on to the importer

    def write_cache(obj_path, mtl_path, textured_actors):
        seen["written"].append(textured_actors)

    monkeypatch.setattr(photo_mesh.cache, "cached_actors", cached_actors)
    monkeypatch.setattr(photo_mesh.cache, "write_cache", write_cache)
    return seen


def read(model, *, full_resolution: bool):
    """Run one load, with the texture cap pulled down to something a test can hold."""
    FakeImporter.actors = [textured_actor()]
    loader = PhotoMeshLoader(model, full_resolution=full_resolution)
    loader.MAX_TEXTURE_DIM = CAP
    return loader._read()


def texture_dims(mesh) -> list[int]:
    return [max(actor.GetTexture().GetInput().GetDimensions()[:2]) for actor in mesh.actors]


def test_the_capped_read_is_cached_both_ways(model, calls):
    """The 6G path: look in the cache, cap the textures, and put them back."""
    mesh = read(model, full_resolution=False)

    assert calls["read"] == 1
    assert len(calls["written"]) == 1
    assert texture_dims(mesh) == [CAP]


def test_the_full_resolution_read_touches_no_cache(model, calls):
    """The 10G path: the cache is not read, and nothing is written back to it."""
    read(model, full_resolution=True)

    assert calls["read"] == 0
    assert calls["written"] == []


def test_the_full_resolution_read_keeps_the_textures_whole(model, calls):
    """Nothing is downscaled, however far past the cap the texture is."""
    mesh = read(model, full_resolution=True)

    assert texture_dims(mesh) == [TEXTURE_DIM]


def test_the_default_read_is_the_capped_one(model):
    """6G is what a loader built without the flag does, and must stay that way."""
    assert PhotoMeshLoader(model).full_resolution is False
