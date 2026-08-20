"""ViewScope VTK viewer with camera flipping and a display mode dropdown.

Run from the repo root:

    uv run python view_vtk.py

Mouse:
    left drag      orbit          middle drag   pan
    scroll         zoom           click buttons along the bottom

Keyboard:
    n / Right      next camera
    p / Left       previous camera
    o              free orbit overview
    1 2 3 4        textured / geometry / targets / all
    q              quit
"""

import numpy as np
import vtk
from vtk.util import numpy_support as vtknp

import viewscope_core as vc

DATA = "data/kiri"
WIDTH, HEIGHT = 1368, 912
YFOV_DEG = 53.1301

MODE_TEXTURED = "Textured mesh"
MODE_GEOMETRY = "Geometry (.obj)"
MODE_TARGETS = "Target values"
MODE_ALL = "All three"
MODES = [MODE_TEXTURED, MODE_GEOMETRY, MODE_TARGETS, MODE_ALL]


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
    lut = None

    if scalars is not None:
        vals = np.ascontiguousarray(scalars, dtype=np.float32)
        arr = vtknp.numpy_to_vtk(vals, deep=True)
        arr.SetName("score")
        out.GetPointData().SetScalars(arr)
        lut = vtk.vtkLookupTable()
        lut.SetHueRange(0.667, 0.0)  # blue low, red high
        lut.Build()
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(float(vals.min()), float(vals.max()))
        mapper.ScalarVisibilityOn()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetPointSize(size)
    return actor, lut


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
    +Y up. VTK wants a position, a focal point along the view direction, and
    an up vector, so we read the basis out of the rotation block.
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
# display modes
# --------------------------------------------------------------------------

class DisplayModes:
    """Switches which layers are drawn and how the mesh is shaded."""

    def __init__(self, window, mesh_actor, texture, cloud_actor, scalar_bar):
        self.window = window
        self.mesh_actor = mesh_actor
        self.texture = texture
        self.cloud_actor = cloud_actor
        self.scalar_bar = scalar_bar
        self.mode = MODE_ALL

    def set(self, mode):
        self.mode = mode
        prop = self.mesh_actor.GetProperty()
        mapper = self.mesh_actor.GetMapper()

        show_mesh = mode in (MODE_TEXTURED, MODE_GEOMETRY, MODE_ALL)
        show_cloud = mode in (MODE_TARGETS, MODE_ALL)

        self.mesh_actor.SetVisibility(show_mesh)
        self.cloud_actor.SetVisibility(show_cloud)
        if self.scalar_bar is not None:
            self.scalar_bar.SetVisibility(show_cloud)

        if mode == MODE_GEOMETRY:
            # Raw tessellation: no texture, no vertex colours, edges drawn.
            self.mesh_actor.SetTexture(None)
            mapper.ScalarVisibilityOff()
            prop.SetRepresentationToSurface()
            prop.SetColor(0.62, 0.64, 0.70)
            prop.EdgeVisibilityOn()
            prop.SetEdgeColor(0.15, 0.16, 0.20)
            prop.SetLineWidth(1.0)
        elif show_mesh:
            self.mesh_actor.SetTexture(self.texture)
            mapper.ScalarVisibilityOn()
            prop.SetRepresentationToSurface()
            prop.SetColor(1.0, 1.0, 1.0)
            prop.EdgeVisibilityOff()

        # In targets-only mode a dense cloud reads better slightly larger.
        self.cloud_actor.GetProperty().SetPointSize(3.0 if mode == MODE_TARGETS else 2.0)
        self.window.Render()


# --------------------------------------------------------------------------
# camera flipping
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
        self.index = None
        self.overview = None

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
        self.hud.SetInput("Overview")
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
# 2D controls
# --------------------------------------------------------------------------

def _frame(x, y, width, height, rgb):
    """A rectangle outline as a vtkActor2D in display coordinates."""
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
    actor = vtk.vtkActor2D()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*rgb)
    return actor


def _label(text, x, y, size=18, rgb=(0.9, 0.9, 0.9)):
    actor = vtk.vtkTextActor()
    actor.SetInput(text)
    actor.SetDisplayPosition(x, y)
    prop = actor.GetTextProperty()
    prop.SetFontSize(size)
    prop.SetColor(*rgb)
    return actor


class TextButton:
    """A label plus a clickable rectangle in display coordinates."""

    def __init__(self, label, x, y, width, height, callback):
        self.x, self.y, self.width, self.height = x, y, width, height
        self.callback = callback
        self.actor = _label(label, x + 12, y + 10)
        self.frame = _frame(x, y, width, height, (0.55, 0.55, 0.60))

    def actors(self):
        return [self.frame, self.actor]

    def hit(self, mx, my):
        return self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height


class DropDown:
    """A header that expands into a list of options on click.

    VTK has no combo box, so this is a header button plus one hidden
    TextButton per option. The options stack upwards from the header so a
    control anchored near the bottom edge stays on screen.
    """

    def __init__(self, x, y, width, height, options, initial, on_choose):
        self.x, self.y, self.width, self.height = x, y, width, height
        self.options = options
        self.on_choose = on_choose
        self.open = False
        self.current = initial

        self.header_frame = _frame(x, y, width, height, (0.75, 0.75, 0.82))
        self.header_label = _label(self._header_text(), x + 12, y + 10)

        self.items = []
        for i, option in enumerate(options):
            iy = y + height * (i + 1) + 4
            item = TextButton(option, x, iy, width, height, self._make_choice(option))
            for actor in item.actors():
                actor.VisibilityOff()
            self.items.append(item)

    def _header_text(self):
        return f"{self.current}   v"

    def _make_choice(self, option):
        def choose():
            self.current = option
            self.header_label.SetInput(self._header_text())
            self.set_open(False)
            self.on_choose(option)
        return choose

    def actors(self):
        out = [self.header_frame, self.header_label]
        for item in self.items:
            out.extend(item.actors())
        return out

    def set_open(self, is_open):
        self.open = is_open
        for item in self.items:
            for actor in item.actors():
                actor.SetVisibility(is_open)

    def select(self, option):
        """Programmatic selection, for the number key shortcuts."""
        self._make_choice(option)()

    def handle_click(self, mx, my):
        """Return True if this widget consumed the click."""
        if self.open:
            for item in self.items:
                if item.hit(mx, my):
                    item.callback()
                    return True
            self.set_open(False)
            return True
        header_hit = (
            self.x <= mx <= self.x + self.width
            and self.y <= my <= self.y + self.height
        )
        if header_hit:
            self.set_open(True)
            return True
        return False


# --------------------------------------------------------------------------

def main():
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.03, 0.03, 0.05)

    mesh = vc.load_scene(f"{DATA}/scene.obj")
    diagonal = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(trimesh_to_polydata(mesh))
    mesh_actor = vtk.vtkActor()
    mesh_actor.SetMapper(mapper)
    texture = texture_from_mesh(mesh)
    if texture is not None:
        mesh_actor.SetTexture(texture)
    renderer.AddActor(mesh_actor)

    targets, _normals = vc.load_targets(f"{DATA}/targets.ply")
    plan = vc.load_plan(f"{DATA}/plan.json")

    scalars = None
    try:
        scores = vc.load_scores(f"{DATA}/scores.npz", len(targets), len(plan.positions))
        scalars = scores.score_8
    except Exception as exc:
        print(f"scores unavailable, drawing targets unshaded: {exc}")

    cloud_actor, lut = point_cloud_actor(targets, scalars)
    renderer.AddActor(cloud_actor)

    scalar_bar = None
    if lut is not None:
        scalar_bar = vtk.vtkScalarBarActor()
        scalar_bar.SetLookupTable(lut)
        scalar_bar.SetTitle("score_8")
        scalar_bar.SetNumberOfLabels(5)
        scalar_bar.SetWidth(0.06)
        scalar_bar.SetHeight(0.35)
        scalar_bar.SetPosition(0.92, 0.55)
        renderer.AddActor2D(scalar_bar)

    glyph_actors = []
    for i in range(len(plan.positions)):
        v, f, colors, edges = vc.camera_glyph(
            plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
        )
        actor = glyph_actor(v, f, colors, edges)
        glyph_actors.append(actor)
        renderer.AddActor(actor)

    hud = _label("Overview", 20, HEIGHT - 40, size=20, rgb=(0.95, 0.95, 0.95))
    renderer.AddActor2D(hud)

    window = vtk.vtkRenderWindow()
    window.SetSize(WIDTH, HEIGHT)
    window.SetWindowName("ViewScope")
    window.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    display = DisplayModes(window, mesh_actor, texture, cloud_actor, scalar_bar)
    flipper = CameraFlipper(renderer, window, plan, glyph_actors, hud, diagonal)

    dropdown = DropDown(
        WIDTH - 260, 20, 240, 40, MODES, MODE_ALL, display.set
    )
    for actor in dropdown.actors():
        renderer.AddActor2D(actor)

    buttons = [
        TextButton("< Prev", 20, 20, 110, 40, flipper.prev),
        TextButton("Next >", 145, 20, 110, 40, flipper.next),
        TextButton("Overview", 270, 20, 130, 40, flipper.show_overview),
    ]
    for b in buttons:
        for actor in b.actors():
            renderer.AddActor2D(actor)

    def on_click(obj, _event):
        mx, my = obj.GetEventPosition()
        # The dropdown gets first refusal: while open it covers other controls.
        if dropdown.handle_click(mx, my):
            window.Render()
            return
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
        elif key in ("1", "2", "3", "4"):
            dropdown.select(MODES[int(key) - 1])
            window.Render()

    interactor.AddObserver("LeftButtonPressEvent", on_click, 1.0)
    interactor.AddObserver("KeyPressEvent", on_key)

    renderer.ResetCamera()
    flipper.show_overview()
    display.set(MODE_ALL)
    window.Render()
    interactor.Start()


if __name__ == "__main__":
    main()