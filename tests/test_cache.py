# Unit tests for src/viewscope/data/cache.py

import vtk

import viewscope.data.cache as cache


def polydata() -> vtk.vtkPolyData:
    sphere = vtk.vtkSphereSource()
    sphere.Update()
    return sphere.GetOutput()


def image(dim: int = 8) -> vtk.vtkImageData:
    data = vtk.vtkImageData()
    data.SetDimensions(dim, dim, 1)
    data.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 3)
    return data


def source(tmp_path, body: str = "v 0 0 0\n"):
    """An OBJ and its MTL on disk, so the fingerprint has real files to read."""
    obj = tmp_path / "model.obj"
    obj.write_text(body)
    mtl = tmp_path / "model.mtl"
    mtl.write_text("newmtl material_0\n")
    return obj, mtl


def test_a_written_set_reads_back_with_its_textures(tmp_path):
    """The round trip the fast path depends on: geometry and texture both survive."""
    obj, mtl = source(tmp_path)
    cache.write_cache(obj, mtl, [(polydata(), image()), (polydata(), image())])

    cached = cache.cached_actors(obj, mtl)
    assert cached is not None and len(cached) == 2

    actors = cache.read_geometry_cache(cached)
    assert len(actors) == 2
    assert all(actor.GetTexture() is not None for actor in actors)
    assert all(actor.GetMapper().GetInput().GetNumberOfCells() for actor in actors)


def test_the_two_variants_do_not_collide_on_disk(tmp_path):
    """
    A capped set must never answer a full-resolution read. They share a
    fingerprint - it is the same OBJ - and are told apart by variant alone.
    """
    obj, mtl = source(tmp_path)
    cache.write_cache(obj, mtl, [(polydata(), image(8))], cache.VARIANT_CAPPED)

    assert cache.cached_actors(obj, mtl, cache.VARIANT_CAPPED) is not None
    assert cache.cached_actors(obj, mtl, cache.VARIANT_FULL) is None

    cache.write_cache(obj, mtl, [(polydata(), image(16))], cache.VARIANT_FULL)

    capped = cache.cached_actors(obj, mtl, cache.VARIANT_CAPPED)
    full = cache.cached_actors(obj, mtl, cache.VARIANT_FULL)
    assert capped is not None and full is not None
    assert capped[0].geometry_path != full[0].geometry_path

    dims = [
        max(cache.read_geometry_cache(entry)[0].GetTexture().GetInput().GetDimensions()[:2])
        for entry in (capped, full)
    ]
    assert dims == [8, 16]


def test_a_stale_set_is_not_a_hit(tmp_path):
    """Rewriting the OBJ changes the fingerprint, so the old set is passed over."""
    obj, mtl = source(tmp_path)
    cache.write_cache(obj, mtl, [(polydata(), image())])
    assert cache.cached_actors(obj, mtl) is not None

    obj.write_text("v 1 1 1\nv 2 2 2\n")
    assert cache.cached_actors(obj, mtl) is None


def test_the_read_reports_progress_per_actor(tmp_path):
    """
    Without this the bar sits at 5% for the whole read - seconds on the capped
    set, and four times that on the full-resolution one - and reads as a hang.
    """
    obj, mtl = source(tmp_path)
    cache.write_cache(obj, mtl, [(polydata(), image()) for _ in range(3)])

    cached = cache.cached_actors(obj, mtl)
    assert cached is not None

    seen = []
    cache.read_geometry_cache(cached, lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_the_read_still_works_without_a_progress_callback(tmp_path):
    """The callback is optional; nothing in cache.py may require one."""
    obj, mtl = source(tmp_path)
    cache.write_cache(obj, mtl, [(polydata(), image())])

    cached = cache.cached_actors(obj, mtl)
    assert cached is not None
    assert len(cache.read_geometry_cache(cached)) == 1
