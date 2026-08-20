
import viewscope_core as vc

import numpy as np

import vtk
from vtk.util import numpy_support as vtknp

DATA = "data/kiri"
WIDTH, HEIGHT = 1368, 912 # these are values from the readme.txt
YFOV_DEG = 53.1301
 # ref:
 # r = vc.SceneRenderer(mesh, 1368, 912, 53.1301)
 # See render.py for the implementation of SceneRenderer

MODE_TEXTURED = "Textured mesh"
MODE_GEOMETRY = "Geometry (.obj)"
MODE_TARGETS = "Target values"
MODE_ALL = "All three"
MODES = [MODE_TEXTURED, MODE_GEOMETRY, MODE_TARGETS, MODE_ALL]

def format_cells(indices, n_per_cell):
    """Numpy and trimesh represent connectivity as a 2D array. VTK needs a single flat stream 
    changing this:
        [[0, 1, 2],
        [1, 3, 2],
        [2, 3, 4]]
    into this:
        [3, 0, 1, 2,  3, 1, 3, 2,  3, 2, 3, 4]

        n_per_cell
          """

    idx = np.ascontiguousarray(indices, dtype=np.int64)
    # C-contiguous memory and 64 bit ints

    # vtk has its own lib for converting numpy arrays to vtk cells
    # read: https://docs.vtk.org/en/latest/api/python/vtkmodules/vtkmodules.util.numpy_support.html


    padded = np.colum_stack(
        [np.full(len(idx), n_per_cell, dtype=np.int64), idx]
    ).ravel()
    # ravel flattens the array into a 1D array, which is what VTK expects for cell connectivity

    cells = vtk.vtkCellArray()

    # array converts to vtkTypeArray. vtkIdType is a 64-bit standard. 
    # deep = True means that the data is copied, not just referenced. This is important because VTK will manage its own memory for the cells.
    # Python can free the original numpy array. VTK will still have its own copy of the data.

    array = vtknp.numpy_to_vtkIdTypeArray(padded, deep=True)

    cells.SetCells(len(idx), array)
    # How many cells to expect, and the array of cell connectivity data.

    return cells

def points(array):
    """Convert a numpy array of points to a vtkPoints object."""

    vtk_points = vtk.vtkPoints()
    array = np.ascontiguousarray(array, dtype=np.float64)
    # again transforms the array into a C-contiguous array of 64-bit floats, which is what VTK expects for point coordinates.
    vtk_points.SetData(vtknp.numpy_to_vtk(array, deep=True))
    return vtk_points


def trimesh_to_polydata(mesh):
    """Convert a trimesh object to a vtkPolyData object."""

    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points(mesh.vertices))
    polydata.SetPolys(format_cells(mesh.faces, 3)) # 3 because we are dealing with triangles

    kind = getattr(mesh.visual, "kind", None)

    if kind == "vertex":
        # If the mesh has vertex colors, we can add them to the polydata
        rgb = np.ascontiguousarray(mesh.visual.vertex_colors[:, :3], dtype=np.uint8)
        





        colors = np.ascontiguousarray(mesh.visual.vertex_colors[:, :3], dtype=np.uint8)
        array = vtknp.numpy_to_vtk(colors, deep=True)
        array.SetName("Colors")
        polydata.GetPointData().SetScalars(array)



    









