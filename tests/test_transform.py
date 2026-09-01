"""
numpy / trimesh -> VTK conversions.

transform.py is pure functions with no Qt, no actors and no application state,
so all of it runs headless. It is also where a silent data-shape mistake would
turn into an empty or scrambled render, which is hard to spot by eye.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
import trimesh.visual
import vtk
from PIL import Image

from viewscope import transform

# -- Primitives --------------------------------------------------------


def test_points_carries_every_coordinate():
    array = np.array([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]])

    pts = transform.points(array)

    assert pts.GetNumberOfPoints() == 2
    assert pts.GetPoint(0) == (0.0, 1.0, 2.0)
    assert pts.GetPoint(1) == (3.0, 4.0, 5.0)


def test_points_accepts_integers():
    """Positions arrive as ints from some readers; VTK needs doubles."""
    pts = transform.points(np.array([[1, 2, 3]]))

    assert pts.GetPoint(0) == (1.0, 2.0, 3.0)


def test_cells_prefixes_each_cell_with_its_size():
    """VTK's legacy cell format is [n, i0, i1, ...] per cell."""
    array = transform.cells(np.array([[0, 1, 2], [2, 3, 0]]), 3)

    assert array.GetNumberOfCells() == 2

    ids = vtk.vtkIdList()
    array.GetCellAtId(0, ids)
    assert [ids.GetId(i) for i in range(ids.GetNumberOfIds())] == [0, 1, 2]


def test_cells_handles_two_point_lines():
    array = transform.cells(np.array([[0, 1], [1, 2]]), 2)

    assert array.GetNumberOfCells() == 2


# -- Meshes ------------------------------------------------------------


def test_trimesh_to_polydata_keeps_the_geometry(sample_mesh):
    poly = transform.trimesh_to_polydata(sample_mesh)

    assert poly.GetNumberOfPoints() == len(sample_mesh.vertices)
    assert poly.GetNumberOfPolys() == len(sample_mesh.faces)


def test_trimesh_to_polydata_carries_vertex_colours(sample_mesh):
    mesh = sample_mesh.copy()
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        vertex_colors=np.tile([255, 0, 0, 255], (len(mesh.vertices), 1)).astype(np.uint8),
    )

    poly = transform.trimesh_to_polydata(mesh)

    scalars = poly.GetPointData().GetScalars()
    assert scalars is not None
    assert scalars.GetName() == "Colors"
    assert scalars.GetNumberOfComponents() == 3
    assert scalars.GetTuple3(0) == (255.0, 0.0, 0.0)


def test_trimesh_to_polydata_carries_uvs(sample_mesh):
    mesh = sample_mesh.copy()
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2), dtype=np.float32)
    )

    poly = transform.trimesh_to_polydata(mesh)

    tcoords = poly.GetPointData().GetTCoords()
    assert tcoords is not None
    assert tcoords.GetNumberOfTuples() == len(mesh.vertices)


def test_trimesh_to_polydata_leaves_a_plain_mesh_unpainted(sample_mesh):
    """A box has no colours and no UVs, so neither array should appear."""
    mesh = sample_mesh.copy()
    mesh.visual = trimesh.visual.TextureVisuals(uv=None)

    poly = transform.trimesh_to_polydata(mesh)

    assert poly.GetPointData().GetTCoords() is None


# -- Textures ----------------------------------------------------------


def test_texture_from_mesh_is_none_without_an_image(sample_mesh):
    assert transform.texture_from_mesh(sample_mesh) is None


def test_texture_from_mesh_builds_a_texture(sample_mesh):
    mesh = sample_mesh.copy()
    image = Image.new("RGB", (4, 2), color=(10, 20, 30))
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2), dtype=np.float32),
        image=image,
    )

    texture = transform.texture_from_mesh(mesh)

    assert texture is not None
    assert texture.GetInput().GetDimensions() == (4, 2, 1)


def test_texture_from_mesh_flips_the_image(sample_mesh):
    """
    Image rows run top-down, VTK textures run bottom-up. Getting this wrong
    renders the texture upside down, which no assertion on size would catch.
    """
    mesh = sample_mesh.copy()
    image = Image.new("RGB", (1, 2))
    image.putpixel((0, 0), (255, 0, 0))  # top row
    image.putpixel((0, 1), (0, 0, 255))  # bottom row
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2), dtype=np.float32),
        image=image,
    )

    texture = transform.texture_from_mesh(mesh)

    scalars = texture.GetInput().GetPointData().GetScalars()
    assert scalars.GetTuple3(0) == (0.0, 0.0, 255.0)  # bottom row lands first


# -- Point clouds and glyphs -------------------------------------------


def test_cloud_polydata_makes_every_point_renderable():
    """Points without vertex cells render as nothing at all."""
    poly = transform.cloud_polydata(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]))

    assert poly.GetNumberOfPoints() == 2
    assert poly.GetNumberOfVerts() == 2


def test_glyph_polydata_assembles_faces_and_edges():
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    faces = np.array([[0, 1, 2]])
    edges = np.array([[0, 1], [1, 2]])
    colours = np.tile([255, 255, 0], (3, 1))

    poly = transform.glyph_polydata(vertices, faces, colours, edges)

    assert poly.GetNumberOfPoints() == 3
    assert poly.GetNumberOfPolys() == 1
    assert poly.GetNumberOfLines() == 2
    assert poly.GetPointData().GetScalars().GetTuple3(0) == (255.0, 255.0, 0.0)


def test_glyph_polydata_tolerates_missing_pieces():
    """Wireframe-only glyphs pass no faces; the call must still work."""
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    poly = transform.glyph_polydata(vertices, None, None, np.array([[0, 1]]))

    assert poly.GetNumberOfPolys() == 0
    assert poly.GetNumberOfLines() == 1
    assert poly.GetPointData().GetScalars() is None


def test_glyph_polydata_ignores_mismatched_colours():
    """One colour per vertex, or none -- never a partial array."""
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])

    poly = transform.glyph_polydata(vertices, None, np.array([[255, 0, 0]]), None)

    assert poly.GetPointData().GetScalars() is None


# -- Camera poses ------------------------------------------------------


def test_apply_pose_places_the_camera(renderer):
    camera = renderer.GetActiveCamera()
    pose = np.eye(4)
    pose[:3, 3] = [1.0, 2.0, 3.0]

    transform.apply_pose(camera, pose, yfov_deg=53.0, distance=10.0)

    assert camera.GetPosition() == (1.0, 2.0, 3.0)
    assert camera.GetViewAngle() == 53.0


def test_apply_pose_looks_down_minus_z(renderer):
    """
    OpenGL convention: the camera looks along its own -Z with +Y up. An
    identity pose at the origin therefore looks towards -Z in world space.
    """
    camera = renderer.GetActiveCamera()

    transform.apply_pose(camera, np.eye(4), yfov_deg=53.0, distance=5.0)

    assert np.allclose(camera.GetFocalPoint(), [0.0, 0.0, -5.0])
    assert np.allclose(camera.GetViewUp(), [0.0, 1.0, 0.0])


def test_apply_pose_scales_the_far_plane_with_the_scene(renderer):
    """A far plane fixed at 100 would clip anything bigger than the default."""
    camera = renderer.GetActiveCamera()

    transform.apply_pose(camera, np.eye(4), yfov_deg=53.0, distance=500.0)

    near, far = camera.GetClippingRange()
    assert near == pytest.approx(0.1)
    assert far == pytest.approx(5000.0)


def test_apply_pose_keeps_a_floor_under_the_far_plane(renderer):
    """A tiny scene must not end up with a far plane in front of the model."""
    camera = renderer.GetActiveCamera()

    transform.apply_pose(camera, np.eye(4), yfov_deg=53.0, distance=0.5)

    assert camera.GetClippingRange()[1] == pytest.approx(100.0)


def test_apply_pose_matches_the_library_pose(renderer):
    """A pose straight out of vc.camera_pose must land where it says."""
    import viewscope_core as vc

    pose = vc.camera_pose([3.0, 0.0, 0.0], yaw_deg=180.0, pitch_deg=0.0)
    camera = renderer.GetActiveCamera()

    transform.apply_pose(camera, pose, yfov_deg=53.0, distance=3.0)

    assert np.allclose(camera.GetPosition(), [3.0, 0.0, 0.0])
    assert np.allclose(camera.GetFocalPoint(), [0.0, 0.0, 0.0], atol=1e-9)
