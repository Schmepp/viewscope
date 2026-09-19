# Unit tests for src/viewscope/scene/photo_mesh.py

import os

# Must be set before Qt picks a platform plugin, so these run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass, field

import pytest
import vtk

from viewscope.data import cache
from viewscope.scene import PhotoMeshLoader, photo_mesh

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


@dataclass
class CacheCalls:
    """What one read asked of the disk cache, and under which variant."""

    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    written_textures: list[list] = field(default_factory=list)


@pytest.fixture
def calls(monkeypatch):
    """Swap the importer and the disk cache out, and record what the read asked of them."""
    seen = CacheCalls()

    monkeypatch.setattr(photo_mesh, "vtkOBJImporter", FakeImporter)

    def cached_actors(obj_path, mtl_path, variant=cache.VARIANT_CAPPED):
        seen.reads.append(variant)
        return None  # never a hit, so the read always goes on to the importer

    def write_cache(obj_path, mtl_path, textured_actors, variant=cache.VARIANT_CAPPED):
        seen.writes.append(variant)
        seen.written_textures.append(textured_actors)

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

    assert calls.reads == [cache.VARIANT_CAPPED]
    assert calls.writes == [cache.VARIANT_CAPPED]
    assert texture_dims(mesh) == [CAP]


def test_the_full_resolution_read_is_cached_both_ways(model, calls):
    """The 10G path is cached too, under its own variant rather than the capped one."""
    read(model, full_resolution=True)

    assert calls.reads == [cache.VARIANT_FULL]
    assert calls.writes == [cache.VARIANT_FULL]


def test_the_two_budgets_never_share_a_cached_set(model, calls):
    """
    The whole point of the variant: 10G must not be handed 6G's capped pixels,
    which is the one way caching it could make it quietly wrong.
    """
    read(model, full_resolution=False)
    read(model, full_resolution=True)

    assert calls.reads == [cache.VARIANT_CAPPED, cache.VARIANT_FULL]
    assert cache.VARIANT_CAPPED != cache.VARIANT_FULL


def test_every_read_caches_the_texture_it_ended_up_wearing(model, calls):
    """
    Both budgets hand the cache a real image, at the size that read produced.
    A texture was previously only cached when it had been downscaled, so one
    already under the cap - and every full-resolution texture - came back from
    the cache wearing nothing at all.
    """
    read(model, full_resolution=False)
    read(model, full_resolution=True)

    capped, full = calls.written_textures
    assert max(capped[0][1].GetDimensions()[:2]) == CAP
    assert max(full[0][1].GetDimensions()[:2]) == TEXTURE_DIM


def test_the_full_resolution_read_keeps_the_textures_whole(model, calls):
    """Nothing is downscaled, however far past the cap the texture is."""
    mesh = read(model, full_resolution=True)

    assert texture_dims(mesh) == [TEXTURE_DIM]


def test_the_default_read_is_the_capped_one(model):
    """6G is what a loader built without the flag does, and must stay that way."""
    assert PhotoMeshLoader(model).full_resolution is False
