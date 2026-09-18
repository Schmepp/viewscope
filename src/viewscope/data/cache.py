"""
Converts the slow-to-parse OBJ into VTK's binary .vtp format the first
time a bundle is opened, so every load after the first skips vtkOBJImporter's
ASCII parsing entirely.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import vtk


def _cache_dir(obj_path: Path) -> Path:
    return obj_path.parent / ".viewscope_cache"


@dataclass(frozen=True)
class CachedActor:
    """
    Represents one actor's cached geometry file and the texture file (if any) it
    should be dressed in.
    """

    geometry_path: Path
    texture_path: Path | None


def _fingerprint(obj_path: Path, mtl_path: Path | None) -> str:
    """Cheap validity check: size + mtime of the source files."""
    parts = [str(obj_path.stat().st_size), str(obj_path.stat().st_mtime_ns)]
    if mtl_path is not None and mtl_path.exists():
        parts += [str(mtl_path.stat().st_size), str(mtl_path.stat().st_mtime_ns)]

    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# The two ways a model is read in, and the mark each leaves on its cache files.
# A capped read and a full-resolution read of the same OBJ hold different
# pixels, so they cannot share one cached set: the capped read stays unmarked,
# which is what every cache written before this existed already looks like, and
# the full-resolution read carries its own tag beside the fingerprint. The
# fingerprint says which source this came from; the variant says how it was
# read.
VARIANT_CAPPED = ""
VARIANT_FULL = "full"


def _stem(obj_path: Path, fingerprint: str, variant: str) -> str:
    """The prefix every file in one cached set shares."""
    parts = [obj_path.stem, fingerprint]
    if variant:
        parts.append(variant)

    return ".".join(parts)


def _meta_path(obj_path: Path, fingerprint: str, variant: str) -> Path:
    """Stores metadata of the cached files - such as the actor count."""
    return _cache_dir(obj_path) / f"{_stem(obj_path, fingerprint, variant)}.json"


def _geometry_path(obj_path: Path, fingerprint: str, variant: str, index: int) -> Path:
    return _cache_dir(obj_path) / f"{_stem(obj_path, fingerprint, variant)}.{index}.vtp"


def _texture_path(obj_path: Path, fingerprint: str, variant: str, index: int) -> Path:
    return _cache_dir(obj_path) / f"{_stem(obj_path, fingerprint, variant)}.{index}.vti"


def texture_source_path(texture: vtk.vtkTexture | None) -> Path | None:
    """The file an already-loaded vtkTexture was read from, if any."""
    if texture is None:
        return None

    algorithm = texture.GetInputAlgorithm()
    get_file_name = getattr(algorithm, "GetFileName", None) if algorithm is not None else None
    if get_file_name is None:
        return None

    filename = get_file_name()
    return Path(filename) if filename else None


def cached_actors(
    obj_path: Path, mtl_path: Path | None, variant: str = VARIANT_CAPPED
) -> list[CachedActor] | None:
    """
    The cached actor list for this exact source read this exact way, or None if
    there isn't a valid one (missing, stale, or a geometry file has since gone
    missing). A cache written for the other variant does not count as a hit:
    handing capped textures to a full-resolution read would quietly give it the
    downscaled pixels it was opened to avoid.
    """
    if not _cache_dir(obj_path).exists():
        return None

    fingerprint = _fingerprint(obj_path, mtl_path)
    meta_path = _meta_path(obj_path, fingerprint, variant)
    if not meta_path.exists():
        return None

    try:
        entries = json.loads(meta_path.read_text())
    except OSError, json.JSONDecodeError:
        return None

    actors = []
    for entry in entries:
        geometry_path = Path(entry["geometry"])
        if not geometry_path.exists():
            return None  # Incomplete cache; treat as absent rather than partial

        texture_path = entry.get("texture")
        actors.append(CachedActor(geometry_path, Path(texture_path) if texture_path else None))

    return actors


def write_cache(
    obj_path: Path,
    mtl_path: Path | None,
    textured_actors: list[tuple[vtk.vtkPolyData, vtk.vtkImageData | None]],
    variant: str = VARIANT_CAPPED,
):
    """
    Write each actor's polydata as binary .vtp, plus a manifest recording
    how many actors there were and which texture (if any) each one wore.
    """
    folder = _cache_dir(obj_path)
    folder.mkdir(exist_ok=True)
    fingerprint = _fingerprint(obj_path, mtl_path)

    manifest = []
    for i, (polydata, image) in enumerate(textured_actors):
        geometry_path = _geometry_path(obj_path, fingerprint, variant, i)
        geom_writer = vtk.vtkXMLPolyDataWriter()
        geom_writer.SetFileName(str(geometry_path))
        geom_writer.SetInputData(polydata)
        geom_writer.SetDataModeToBinary()
        geom_writer.Write()

        texture_path = None
        if image is not None:
            texture_path = _texture_path(obj_path, fingerprint, variant, i)
            img_writer = vtk.vtkXMLImageDataWriter()
            img_writer.SetFileName(str(texture_path))
            img_writer.SetInputData(image)
            img_writer.SetDataModeToBinary()
            img_writer.Write()

        manifest.append(
            {
                "geometry": str(geometry_path),
                "texture": str(texture_path) if texture_path is not None else None,
            }
        )

    _meta_path(obj_path, fingerprint, variant).write_text(json.dumps(manifest))


def read_geometry_cache(
    cached: list[CachedActor],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[vtk.vtkActor]:
    """
    Rebuild actors straight from cached geometry & texture files.
    on_progress is called with (done, total) as each actor lands. Reading a
    cached set is seconds of disk - more on the full-resolution variant, whose
    textures are four times the size - and a bar that sits still for that long
    reads as a hang rather than as the fast path it is.
    """
    actors = []
    total = len(cached)

    for entry in cached:
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(entry.geometry_path))
        reader.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(reader.GetOutput())

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        if entry.texture_path is not None and entry.texture_path.exists():
            image_reader = vtk.vtkXMLImageDataReader()
            image_reader.SetFileName(str(entry.texture_path))
            image_reader.Update()

            texture = vtk.vtkTexture()
            texture.SetInputConnection(image_reader.GetOutputPort())
            texture.InterpolateOn()
            actor.SetTexture(texture)

        actors.append(actor)
        if on_progress is not None:
            on_progress(len(actors), total)

    return actors
