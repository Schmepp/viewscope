import viewscope_core as vc

import numpy as np


def main():
    print("Hello world from ViewScope!")

    # NOTE: The code below was copied from the README that came with the
    # scaffold code. This code isn't actually intended to do anything. We're
    # only calling it here to ensure our dev environment is properly setup and
    # that all the required libraries have been imported correctly.


    # scores.npz is the input file
    # load_scores() is a method that checks if the .npz file is structurally sound and if it is it reurns a Scores object.

    # all_scores = vc.load_scores("data/kiri/scores.npz")

    # z = np.load("data/kiri/flyable.npz")
    # shape = tuple(z["shape"])
    # flyable = np.unpackbits(z["bits"], count=int(np.prod(shape))).reshape(shape).astype(bool)

    # idx = np.floor((point - origin) / voxel).astype(int)
    # ok = flyable[idx[0], idx[1], idx[2]]



    # Draw the plan:

    plan = vc.load_plan("data/kiri/plan.json")
    v, f, colors, edges = vc.camera_glyph(
        plan.positions[0], plan.yaws_deg[0], plan.pitches_deg[0]
    )

    # Visibility of a camera against the 60000 targets:

    mesh = vc.load_scene("data/kiri/scene.obj")
    targets, normals = vc.load_targets("data/kiri/targets.ply")
    r = vc.SceneRenderer(mesh, 1368, 912, 53.1301)
    pose = vc.camera_pose([190.0, 105.0, 5.0], 30.0, -20.0)
    _row = vc.camera_visibility(
        r.render_depth(pose), targets, normals, [190.0, 105.0, 5.0], pose, plan.camera
    )


    r.close()

"""Display the ViewScope scene, target cloud and camera plan in a VTK window.

Run from the repo root:

    uv run python view_vtk.py

Controls: left-drag orbit, middle-drag pan, scroll zoom, 'w' wireframe,
's' surface, 'r' reset camera, 'q' quit.
"""

import numpy as np
import vtk
from vtk.util import numpy_support as vtknp

import viewscope_core as vc

DATA = "data/kiri"


def trimesh_to_polydata(mesh):
    """Convert a trimesh.Trimesh into vtkPolyData, carrying colour if present."""
    poly = vtk.vtkPolyData()

    pts = vtk.vtkPoints()
    verts = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    pts.SetData(vtknp.numpy_to_vtk(verts, deep=True))
    poly.SetPoints(pts)

    # VTK cell arrays are flat: [n, i0, i1, i2, n, i0, i1, i2, ...]
    faces = np.ascontiguousarray(mesh.faces, dtype=np.int64)
    padded = np.column_stack(
        [np.full(len(faces), 3, dtype=np.int64), faces]
    ).ravel()
    cells = vtk.vtkCellArray()
    cells.SetCells(len(faces), vtknp.numpy_to_vtkIdTypeArray(padded, deep=True))
    poly.SetPolys(cells)

    kind = getattr(mesh.visual, "kind", None)

    if kind == "vertex":
        rgb = np.ascontiguousarray(mesh.visual.vertex_colors[:, :3], dtype=np.uint8)
        arr = vtknp.numpy_to_vtk(rgb, deep=True)
        arr.SetName("Colors")
        poly.GetPointData().SetScalars(arr)

    elif kind == "texture" and getattr(mesh.visual, "uv", None) is not None:
        uv = np.ascontiguousarray(mesh.visual.uv, dtype=np.float32)
        tc = vtknp.numpy_to_vtk(uv, deep=True)
        tc.SetName("TCoords")
        poly.GetPointData().SetTCoords(tc)

    return poly


def texture_from_mesh(mesh):
    """Build a vtkTexture from the mesh's material image, or None."""
    image = getattr(getattr(mesh.visual, "material", None), "image", None)
    if image is None:
        return None

    # PIL rows run top-down; VTK expects bottom-up.
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)[::-1]
    h, w, _ = rgb.shape

    img = vtk.vtkImageData()
    img.SetDimensions(w, h, 1)
    arr = vtknp.numpy_to_vtk(np.ascontiguousarray(rgb.reshape(-1, 3)), deep=True)
    arr.SetName("rgb")
    img.GetPointData().SetScalars(arr)

    tex = vtk.vtkTexture()
    tex.SetInputData(img)
    tex.InterpolateOn()
    return tex


def point_cloud_actor(points, scalars=None, size=3.0):
    """Render an (N, 3) array as points, optionally coloured by an (N,) scalar."""
    poly = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(vtknp.numpy_to_vtk(np.ascontiguousarray(points, dtype=np.float64), deep=True))
    poly.SetPoints(pts)

    # Without this every point exists but no cell references it, so nothing draws.
    glyph = vtk.vtkVertexGlyphFilter()
    glyph.SetInputData(poly)
    glyph.Update()
    out = glyph.GetOutput()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(out)

    if scalars is not None:
        vals = np.ascontiguousarray(scalars, dtype=np.float32)
        arr = vtknp.numpy_to_vtk(vals, deep=True)
        arr.SetName("score")
        out.GetPointData().SetScalars(arr)

        lut = vtk.vtkLookupTable()
        lut.SetHueRange(0.667, 0.0)  # blue (low) through to red (high)
        lut.Build()
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(float(vals.min()), float(vals.max()))
        mapper.ScalarVisibilityOn()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetPointSize(size)
    return actor


def glyph_actor(v, f, colors, edges):
    """Turn a vc.camera_glyph tuple into a VTK actor."""
    poly = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(vtknp.numpy_to_vtk(np.ascontiguousarray(v, dtype=np.float64), deep=True))
    poly.SetPoints(pts)

    if f is not None and len(f):
        tris = np.ascontiguousarray(f, dtype=np.int64)
        padded = np.column_stack([np.full(len(tris), 3, dtype=np.int64), tris]).ravel()
        polys = vtk.vtkCellArray()
        polys.SetCells(len(tris), vtknp.numpy_to_vtkIdTypeArray(padded, deep=True))
        poly.SetPolys(polys)

    if edges is not None and len(edges):
        segs = np.ascontiguousarray(edges, dtype=np.int64)
        padded = np.column_stack([np.full(len(segs), 2, dtype=np.int64), segs]).ravel()
        lines = vtk.vtkCellArray()
        lines.SetCells(len(segs), vtknp.numpy_to_vtkIdTypeArray(padded, deep=True))
        poly.SetLines(lines)

    if colors is not None and len(colors) == len(v):
        rgb = np.ascontiguousarray(np.asarray(colors)[:, :3], dtype=np.uint8)
        arr = vtknp.numpy_to_vtk(rgb, deep=True)
        arr.SetName("Colors")
        poly.GetPointData().SetScalars(arr)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetLineWidth(2.0)
    return actor


def main_old():
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.03, 0.03, 0.05)

    mesh = vc.load_scene(f"{DATA}/scene.obj")
    mesh_actor = vtk.vtkActor()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(trimesh_to_polydata(mesh))
    mesh_actor.SetMapper(mapper)

    tex = texture_from_mesh(mesh)
    if tex is not None:
        mesh_actor.SetTexture(tex)
    renderer.AddActor(mesh_actor)

    targets, normals = vc.load_targets(f"{DATA}/targets.ply")

    # Colour the cloud by coverage score if the bundle is loadable.
    scalars = None
    try:
        plan = vc.load_plan(f"{DATA}/plan.json")
        scores = vc.load_scores(
            f"{DATA}/scores.npz", len(targets), len(plan.positions)
        )
        scalars = scores.score_8
    except Exception as exc:
        print(f"scores unavailable, drawing targets unshaded: {exc}")
        plan = None

    renderer.AddActor(point_cloud_actor(targets, scalars, size=2.0))

    if plan is not None:
        for i in range(len(plan.positions)):
            v, f, colors, edges = vc.camera_glyph(
                plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
            )
            renderer.AddActor(glyph_actor(v, f, colors, edges))

    window = vtk.vtkRenderWindow()
    window.SetSize(1368, 912)
    window.SetWindowName("ViewScope")
    window.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    renderer.ResetCamera()
    window.Render()
    interactor.Start()

def main_older():
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.03, 0.03, 0.05)

    mesh = vc.load_scene(f"{DATA}/scene.obj")
    mesh_actor = vtk.vtkActor()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(trimesh_to_polydata(mesh))
    mesh_actor.SetMapper(mapper)

    tex = texture_from_mesh(mesh)
    if tex is not None:
        mesh_actor.SetTexture(tex)
    renderer.AddActor(mesh_actor)

    targets, normals = vc.load_targets(f"{DATA}/targets.ply")
    scalars = None
    try:
        plan = vc.load_plan(f"{DATA}/plan.json")
        scores = vc.load_scores(
            f"{DATA}/scores.npz", len(targets), len(plan.positions)
        )
        scalars = scores.score_8
    except Exception as exc:
            print(f"scores unavailable, drawing targets unshaded: {exc}")
            plan = None


    renderer.AddActor(point_cloud_actor(targets, scalars, size=2.0))

  

    window = vtk.vtkRenderWindow()
    window.SetSize(1368, 912)
    window.SetWindowName("ViewScope")
    window.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    renderer.ResetCamera()
    window.Render()
    interactor.Start()

"""ViewScope VTK viewer with camera flipping.

Run from the repo root:

    uv run python view_vtk.py

Click the on-screen buttons, or use the keyboard:
    n / Right  next camera
    p / Left   previous camera
    o          back to the free orbit overview
    w / s      wireframe / surface
    q          quit
"""

import numpy as np
import vtk
from vtk.util import numpy_support as vtknp

import viewscope_core as vc

DATA = "data/kiri"
WIDTH, HEIGHT = 1368, 912
YFOV_DEG = 53.1301


# --------------------------------------------------------------------------
# geometry conversion
# --------------------------------------------------------------------------

def _cells(indices, n_per_cell):
    """Build a vtkCellArray from an (N, n_per_cell) index array."""
    idx = np.ascontiguousarray(indices, dtype=np.int64)
    padded = np.column_stack(
        [np.full(len(idx), n_per_cell, dtype=np.int64), idx]
    ).ravel()
    cells = vtk.vtkCellArray()
    cells.SetCells(len(idx), vtknp.numpy_to_vtkIdTypeArray(padded, deep=True))
    return cells


def _points(array):
    pts = vtk.vtkPoints()
    pts.SetData(vtknp.numpy_to_vtk(np.ascontiguousarray(array, dtype=np.float64), deep=True))
    return pts


def trimesh_to_polydata(mesh):
    poly = vtk.vtkPolyData()
    poly.SetPoints(_points(mesh.vertices))
    poly.SetPolys(_cells(mesh.faces, 3))

    kind = getattr(mesh.visual, "kind", None)
    if kind == "vertex":
        rgb = np.ascontiguousarray(mesh.visual.vertex_colors[:, :3], dtype=np.uint8)
        arr = vtknp.numpy_to_vtk(rgb, deep=True)
        arr.SetName("Colors")
        poly.GetPointData().SetScalars(arr)
    elif kind == "texture" and getattr(mesh.visual, "uv", None) is not None:
        uv = np.ascontiguousarray(mesh.visual.uv, dtype=np.float32)
        tc = vtknp.numpy_to_vtk(uv, deep=True)
        tc.SetName("TCoords")
        poly.GetPointData().SetTCoords(tc)
    return poly


def texture_from_mesh(mesh):
    image = getattr(getattr(mesh.visual, "material", None), "image", None)
    if image is None:
        return None
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)[::-1]
    h, w, _ = rgb.shape
    img = vtk.vtkImageData()
    img.SetDimensions(w, h, 1)
    arr = vtknp.numpy_to_vtk(np.ascontiguousarray(rgb.reshape(-1, 3)), deep=True)
    img.GetPointData().SetScalars(arr)
    tex = vtk.vtkTexture()
    tex.SetInputData(img)
    tex.InterpolateOn()
    return tex


def point_cloud_actor(points, scalars=None, size=2.0):
    poly = vtk.vtkPolyData()
    poly.SetPoints(_points(points))
    glyph = vtk.vtkVertexGlyphFilter()
    glyph.SetInputData(poly)
    glyph.Update()
    out = glyph.GetOutput()

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(out)

    if scalars is not None:
        vals = np.ascontiguousarray(scalars, dtype=np.float32)
        arr = vtknp.numpy_to_vtk(vals, deep=True)
        arr.SetName("score")
        out.GetPointData().SetScalars(arr)
        lut = vtk.vtkLookupTable()
        lut.SetHueRange(0.667, 0.0)
        lut.Build()
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(float(vals.min()), float(vals.max()))
        mapper.ScalarVisibilityOn()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetPointSize(size)
    return actor


def glyph_actor(v, f, colors, edges):
    poly = vtk.vtkPolyData()
    poly.SetPoints(_points(v))
    if f is not None and len(f):
        poly.SetPolys(_cells(f, 3))
    if edges is not None and len(edges):
        poly.SetLines(_cells(edges, 2))
    if colors is not None and len(colors) == len(v):
        rgb = np.ascontiguousarray(np.asarray(colors)[:, :3], dtype=np.uint8)
        arr = vtknp.numpy_to_vtk(rgb, deep=True)
        poly.GetPointData().SetScalars(arr)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetLineWidth(2.0)
    return actor


# --------------------------------------------------------------------------
# pose -> vtkCamera
# --------------------------------------------------------------------------

def apply_pose(camera, pose, yfov_deg, distance):
    """Point a vtkCamera at whatever a 4x4 camera-to-world pose is looking at.

    pyrender / OpenGL convention: the camera looks down its own -Z axis with
    +Y up. VTK instead wants a position, a focal point somewhere along the
    view direction, and an up vector -- so we pull the basis out of the
    rotation block and synthesise a focal point.
    """
    pose = np.asarray(pose, dtype=np.float64)
    position = pose[:3, 3]
    forward = -pose[:3, 2]
    up = pose[:3, 1]

    camera.SetPosition(*position)
    camera.SetFocalPoint(*(position + forward * distance))
    camera.SetViewUp(*up)
    camera.UseHorizontalViewAngleOff()
    camera.SetViewAngle(yfov_deg)
    camera.SetClippingRange(0.1, max(100.0, 10.0 * distance))


# --------------------------------------------------------------------------
# flipping controller
# --------------------------------------------------------------------------

class CameraFlipper:
    """Cycles the viewport through the planned camera poses."""

    def __init__(self, renderer, window, plan, glyph_actors, hud, distance):
        self.renderer = renderer
        self.window = window
        self.plan = plan
        self.glyph_actors = glyph_actors
        self.hud = hud
        self.distance = distance
        self.index = None          # None means the free orbit overview
        self.overview = None       # saved orbit camera state

    def _save_overview(self):
        cam = self.renderer.GetActiveCamera()
        self.overview = (
            cam.GetPosition(), cam.GetFocalPoint(),
            cam.GetViewUp(), cam.GetViewAngle(),
        )

    def show_overview(self):
        if self.overview is not None:
            cam = self.renderer.GetActiveCamera()
            pos, focal, up, angle = self.overview
            cam.SetPosition(*pos)
            cam.SetFocalPoint(*focal)
            cam.SetViewUp(*up)
            cam.SetViewAngle(angle)
            self.renderer.ResetCameraClippingRange()
        self.index = None
        for actor in self.glyph_actors:
            actor.VisibilityOn()
        self.hud.SetInput("Overview  --  n next, p previous, o overview")
        self.window.Render()

    def show(self, index):
        n = len(self.plan.positions)
        if n == 0:
            return
        if self.index is None:
            self._save_overview()

        self.index = index % n
        pose = vc.camera_pose(
            self.plan.positions[self.index],
            self.plan.yaws_deg[self.index],
            self.plan.pitches_deg[self.index],
        )
        apply_pose(self.renderer.GetActiveCamera(), pose, YFOV_DEG, self.distance)

        # Hide the frustum you are sitting inside; it would fill the view.
        for i, actor in enumerate(self.glyph_actors):
            actor.SetVisibility(i != self.index)

        pos = np.asarray(self.plan.positions[self.index], dtype=float)
        self.hud.SetInput(
            f"Camera {self.index + 1} of {n}   "
            f"pos ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})   "
            f"yaw {float(self.plan.yaws_deg[self.index]):.1f}   "
            f"pitch {float(self.plan.pitches_deg[self.index]):.1f}"
        )
        self.window.Render()

    def next(self):
        self.show(0 if self.index is None else self.index + 1)

    def prev(self):
        self.show(-1 if self.index is None else self.index - 1)


# --------------------------------------------------------------------------
# on-screen buttons
# --------------------------------------------------------------------------

class TextButton:
    """A vtkTextActor plus a clickable rectangle in display coordinates."""

    def __init__(self, label, x, y, width, height, callback):
        self.x, self.y = x, y
        self.width, self.height = width, height
        self.callback = callback

        self.actor = vtk.vtkTextActor()
        self.actor.SetInput(label)
        self.actor.SetDisplayPosition(x + 10, y + 8)
        prop = self.actor.GetTextProperty()
        prop.SetFontSize(18)
        prop.SetColor(0.9, 0.9, 0.9)

        self.frame = vtk.vtkActor2D()
        poly = vtk.vtkPolyData()
        pts = vtk.vtkPoints()
        for px, py in ((x, y), (x + width, y), (x + width, y + height), (x, y + height)):
            pts.InsertNextPoint(px, py, 0.0)
        poly.SetPoints(pts)
        lines = vtk.vtkCellArray()
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(a)
            lines.InsertCellPoint(b)
        poly.SetLines(lines)
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        self.frame.SetMapper(mapper)
        self.frame.GetProperty().SetColor(0.55, 0.55, 0.6)

    def hit(self, mx, my):
        return self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height


def main():
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.03, 0.03, 0.05)

    mesh = vc.load_scene(f"{DATA}/scene.obj")
    diagonal = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(trimesh_to_polydata(mesh))
    mesh_actor = vtk.vtkActor()
    mesh_actor.SetMapper(mapper)
    tex = texture_from_mesh(mesh)
    if tex is not None:
        mesh_actor.SetTexture(tex)
    renderer.AddActor(mesh_actor)

    targets, _normals = vc.load_targets(f"{DATA}/targets.ply")
    plan = vc.load_plan(f"{DATA}/plan.json")

    scalars = None
    try:
        scores = vc.load_scores(f"{DATA}/scores.npz", len(targets), len(plan.positions))
        scalars = scores.score_8
    except Exception as exc:
        print(f"scores unavailable, drawing targets unshaded: {exc}")

    renderer.AddActor(point_cloud_actor(targets, scalars))

    glyph_actors = []
    for i in range(len(plan.positions)):
        v, f, colors, edges = vc.camera_glyph(
            plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
        )
        actor = glyph_actor(v, f, colors, edges)
        glyph_actors.append(actor)
        renderer.AddActor(actor)

    hud = vtk.vtkTextActor()
    hud.SetDisplayPosition(20, HEIGHT - 40)
    hud.GetTextProperty().SetFontSize(20)
    hud.GetTextProperty().SetColor(0.95, 0.95, 0.95)
    renderer.AddActor2D(hud)

    window = vtk.vtkRenderWindow()
    window.SetSize(WIDTH, HEIGHT)
    window.SetWindowName("ViewScope")
    window.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    flipper = CameraFlipper(renderer, window, plan, glyph_actors, hud, diagonal)

    buttons = [
        TextButton("< Prev", 20, 20, 110, 40, flipper.prev),
        TextButton("Next >", 145, 20, 110, 40, flipper.next),
        TextButton("Overview", 270, 20, 130, 40, flipper.show_overview),
    ]
    for b in buttons:
        renderer.AddActor2D(b.actor)
        renderer.AddActor2D(b.frame)

    def on_click(obj, _event):
        mx, my = obj.GetEventPosition()
        for b in buttons:
            if b.hit(mx, my):
                b.callback()
                return

    def on_key(obj, _event):
        key = obj.GetKeySym()
        if key in ("n", "Right"):
            flipper.next()
        elif key in ("p", "Left"):
            flipper.prev()
        elif key == "o":
            flipper.show_overview()

    interactor.AddObserver("LeftButtonPressEvent", on_click, 1.0)
    interactor.AddObserver("KeyPressEvent", on_key)

    renderer.ResetCamera()
    flipper.show_overview()
    window.Render()
    interactor.Start()


if __name__ == "__main__":
    main()

