"""
Monolith version of main.py

discard later
"""

from __future__ import annotations

from curses import window
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Must be set before the Qt widget module is imported, so VTK binds to the
# same Qt binding we are using rather than guessing.
import vtkmodules.qt
vtkmodules.qt.PyQtImpl = "PySide6"

import vtk
from vtk.util import numpy_support as vtknp
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from PySide6.QtCore import Qt, QThread, Signal, QSettings, QByteArray
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, QWidget, QVBoxLayout, QFormLayout,
    QComboBox, QLabel, QSlider, QCheckBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QStatusBar, QMessageBox, QGroupBox,
)

import viewscope_core as vc

DATA = "data/kiri"
YFOV_DEG = 53.1301

MODE_TEXTURED = "Textured mesh"
MODE_GEOMETRY = "Geometry (.obj)"
MODE_TARGETS = "Target values"
MODE_ALL = "All three"
MODES = [MODE_TEXTURED, MODE_GEOMETRY, MODE_TARGETS, MODE_ALL]

SCALAR_FIELDS = ["score_8", "score_4", "diversity_8", "diversity_4"]


# ==========================================================================
# geometry conversion  (unchanged from view_vtk.py)
# ==========================================================================

def _points(array):
    pts = vtk.vtkPoints()
    pts.SetData(vtknp.numpy_to_vtk(np.ascontiguousarray(array, dtype=np.float64), deep=True))
    return pts


def _cells(indices, n_per_cell):
    idx = np.ascontiguousarray(indices, dtype=np.int64)
    padded = np.column_stack(
        [np.full(len(idx), n_per_cell, dtype=np.int64), idx]
    ).ravel()
    cells = vtk.vtkCellArray()
    cells.SetCells(len(idx), vtknp.numpy_to_vtkIdTypeArray(padded, deep=True))
    return cells


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


def glyph_actor(v, f, colors, edges):
    poly = vtk.vtkPolyData()
    poly.SetPoints(_points(v))
    if f is not None and len(f):
        poly.SetPolys(_cells(f, 3))
    if edges is not None and len(edges):
        poly.SetLines(_cells(edges, 2))
    if colors is not None and len(colors) == len(v):
        rgb = np.ascontiguousarray(np.asarray(colors)[:, :3], dtype=np.uint8)
        poly.GetPointData().SetScalars(vtknp.numpy_to_vtk(rgb, deep=True))

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetLineWidth(2.0)
    return actor


def apply_pose(camera, pose, yfov_deg, distance):
    """Point a vtkCamera using a 4x4 camera-to-world pose.

    OpenGL convention: the camera looks down its own -Z with +Y up, so the
    rotation block's columns are the camera axes in world space.
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


# ==========================================================================
# background loading
# ==========================================================================

@dataclass
class SceneData:
    mesh: object
    targets: np.ndarray
    normals: np.ndarray
    plan: object
    scores: Optional[object]
    scores_error: Optional[str]


class LoaderThread(QThread):
    """Parses the bundle off the interface thread.

    Only plain trimesh / numpy objects cross back. VTK actors are built on
    the main thread, because the render window's GL context lives there.
    """

    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def run(self):
        try:
            self.progress.emit("Loading scene mesh...")
            mesh = vc.load_scene(f"{DATA}/scene.obj")

            self.progress.emit("Loading targets...")
            targets, normals = vc.load_targets(f"{DATA}/targets.ply")

            self.progress.emit("Loading plan...")
            plan = vc.load_plan(f"{DATA}/plan.json")

            self.progress.emit("Loading scores...")
            scores, scores_error = None, None
            try:
                scores = vc.load_scores(
                    f"{DATA}/scores.npz", len(targets), len(plan.positions)
                )
            except Exception as exc:
                scores_error = str(exc)

            self.loaded.emit(
                SceneData(mesh, targets, normals, plan, scores, scores_error)
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# ==========================================================================
# panels
# ==========================================================================

class DisplayPanel(QWidget):
    """Display mode, scalar field, point size, glyph visibility."""

    mode_changed = Signal(str)
    field_changed = Signal(str)
    point_size_changed = Signal(int)
    glyphs_toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        box = QGroupBox("Scene")
        form = QFormLayout(box)

        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.setCurrentText(MODE_ALL)
        self.mode.currentTextChanged.connect(self.mode_changed)
        form.addRow("Display", self.mode)

        self.field = QComboBox()
        self.field.addItems(SCALAR_FIELDS)
        self.field.currentTextChanged.connect(self.field_changed)
        form.addRow("Colour by", self.field)

        self.point_size = QSlider(Qt.Horizontal)
        self.point_size.setRange(1, 10)
        self.point_size.setValue(2)
        self.point_size.valueChanged.connect(self.point_size_changed)
        form.addRow("Point size", self.point_size)

        self.glyphs = QCheckBox("Show camera frusta")
        self.glyphs.setChecked(True)
        self.glyphs.toggled.connect(self.glyphs_toggled)
        form.addRow(self.glyphs)

        layout.addWidget(box)
        layout.addStretch(1)


class MetricsPanel(QWidget):
    """Read-only figures about the bundle and the current viewpoint."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.rows = {}
        for title, keys in (
            ("Bundle", ["Vertices", "Triangles", "Diagonal", "Targets", "Cameras"]),
            ("Scalar field", ["Field", "Min", "Mean", "Max"]),
            ("Viewpoint", ["Camera", "Position", "Yaw", "Pitch"]),
        ):
            box = QGroupBox(title)
            form = QFormLayout(box)
            for key in keys:
                label = QLabel("--")
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(key, label)
                self.rows[key] = label
            layout.addWidget(box)

        layout.addStretch(1)

    def set(self, key, value):
        if key in self.rows:
            self.rows[key].setText(str(value))


class ViewpointPanel(QTableWidget):
    """One row per planned camera; selecting a row jumps the viewport."""

    camera_picked = Signal(int)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["#", "Position", "Yaw", "Pitch"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.itemSelectionChanged.connect(self._on_selection)
        self._suppress = False

    def populate(self, plan):
        self._suppress = True
        n = len(plan.positions)
        self.setRowCount(n)
        for i in range(n):
            pos = np.asarray(plan.positions[i], dtype=float)
            values = [
                str(i + 1),
                f"{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}",
                f"{float(plan.yaws_deg[i]):.1f}",
                f"{float(plan.pitches_deg[i]):.1f}",
            ]
            for col, text in enumerate(values):
                self.setItem(i, col, QTableWidgetItem(text))
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._suppress = False

    def _on_selection(self):
        if self._suppress:
            return
        rows = self.selectionModel().selectedRows()
        if rows:
            self.camera_picked.emit(rows[0].row())

    def select_row(self, index):
        """Reflect a selection made elsewhere without re-emitting."""
        self._suppress = True
        if index is None:
            self.clearSelection()
        else:
            self.selectRow(index)
        self._suppress = False


# ==========================================================================
# main window
# ==========================================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ViewScope")
        self.resize(1500, 950)

        self.data: Optional[SceneData] = None
        self.mesh_actor = None
        self.cloud_actor = None
        self.cloud_polydata = None
        self.texture = None
        self.lut = None
        self.scalar_bar = None
        self.glyph_actors = []
        self.diagonal = 1.0
        self.camera_index = None
        self.overview_state = None
        self.show_glyphs = True
        self.mode = MODE_ALL

        # --- central viewport -------------------------------------------
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.setCentralWidget(self.vtk_widget)

        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0.03, 0.03, 0.05)
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)

        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        self.interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

        # --- panels ------------------------------------------------------
        self.display_panel = DisplayPanel()
        self.metrics_panel = MetricsPanel()
        self.viewpoint_panel = ViewpointPanel()

        self.docks = {}
        self._add_dock("Viewpoints", self.viewpoint_panel, Qt.LeftDockWidgetArea)
        self._add_dock("Display", self.display_panel, Qt.RightDockWidgetArea)
        self._add_dock("Metrics", self.metrics_panel, Qt.RightDockWidgetArea)

        self.display_panel.mode_changed.connect(self.set_mode)
        self.display_panel.field_changed.connect(self.set_scalar_field)
        self.display_panel.point_size_changed.connect(self.set_point_size)
        self.display_panel.glyphs_toggled.connect(self.set_glyphs_visible)
        self.viewpoint_panel.camera_picked.connect(self.show_camera)

        self._build_actions()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Loading...")

        self._restore_layout()

        # --- load --------------------------------------------------------
        self.loader = LoaderThread()
        self.loader.progress.connect(self.statusBar().showMessage)
        self.loader.loaded.connect(self.on_loaded)
        self.loader.failed.connect(self.on_failed)
        self.loader.start()

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------

    def _add_dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title}")   # required for saveState
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        self.docks[title] = dock
        return dock

    def _build_actions(self):
        toolbar = self.addToolBar("Cameras")
        toolbar.setObjectName("toolbar_cameras")

        self.act_prev = QAction("Previous", self)
        self.act_prev.setShortcuts([QKeySequence("P"), QKeySequence(Qt.Key_Left)])
        self.act_prev.triggered.connect(self.prev_camera)

        self.act_next = QAction("Next", self)
        self.act_next.setShortcuts([QKeySequence("N"), QKeySequence(Qt.Key_Right)])
        self.act_next.triggered.connect(self.next_camera)

        self.act_overview = QAction("Overview", self)
        self.act_overview.setShortcut(QKeySequence("O"))
        self.act_overview.triggered.connect(self.show_overview)

        for act in (self.act_prev, self.act_next, self.act_overview):
            toolbar.addAction(act)
            self.addAction(act)      # keeps shortcuts alive when VTK has focus

        view_menu = self.menuBar().addMenu("&View")
        for title, dock in self.docks.items():
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        camera_menu = self.menuBar().addMenu("&Camera")
        for act in (self.act_prev, self.act_next, self.act_overview):
            camera_menu.addAction(act)

        # Number keys mirror the display combo box.
        for i, mode in enumerate(MODES, start=1):
            act = QAction(mode, self)
            act.setShortcut(QKeySequence(str(i)))
            act.triggered.connect(
                lambda _checked=False, m=mode: self.display_panel.mode.setCurrentText(m)
            )
            self.addAction(act)

    # ------------------------------------------------------------------
    # loading callbacks
    # ------------------------------------------------------------------

    def on_failed(self, message):
        self.statusBar().showMessage("Load failed")
        QMessageBox.critical(self, "ViewScope", f"Could not load the bundle.\n\n{message}")

    def on_loaded(self, data: SceneData):
        self.data = data
        mesh = data.mesh
        self.diagonal = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))

        # mesh actor
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(trimesh_to_polydata(mesh))
        self.mesh_actor = vtk.vtkActor()
        self.mesh_actor.SetMapper(mapper)
        self.texture = texture_from_mesh(mesh)
        if self.texture is not None:
            self.mesh_actor.SetTexture(self.texture)
        self.renderer.AddActor(self.mesh_actor)

        # target cloud
        poly = vtk.vtkPolyData()
        poly.SetPoints(_points(data.targets))
        glyph = vtk.vtkVertexGlyphFilter()
        glyph.SetInputData(poly)
        glyph.Update()
        self.cloud_polydata = glyph.GetOutput()

        cloud_mapper = vtk.vtkPolyDataMapper()
        cloud_mapper.SetInputData(self.cloud_polydata)
        self.cloud_actor = vtk.vtkActor()
        self.cloud_actor.SetMapper(cloud_mapper)
        self.cloud_actor.GetProperty().SetPointSize(2.0)
        self.renderer.AddActor(self.cloud_actor)

        if data.scores is not None:
            self.lut = vtk.vtkLookupTable()
            self.lut.SetHueRange(0.667, 0.0)     # blue low, red high
            self.lut.Build()
            cloud_mapper.SetLookupTable(self.lut)

            self.scalar_bar = vtk.vtkScalarBarActor()
            self.scalar_bar.SetLookupTable(self.lut)
            self.scalar_bar.SetNumberOfLabels(5)
            self.scalar_bar.SetWidth(0.055)
            self.scalar_bar.SetHeight(0.32)
            self.scalar_bar.SetPosition(0.93, 0.58)
            self.renderer.AddActor2D(self.scalar_bar)

            self.set_scalar_field(self.display_panel.field.currentText())
        else:
            self.display_panel.field.setEnabled(False)
            self.metrics_panel.set("Field", "unavailable")
            if data.scores_error:
                print(f"scores unavailable: {data.scores_error}")

        # camera glyphs
        plan = data.plan
        for i in range(len(plan.positions)):
            v, f, colors, edges = vc.camera_glyph(
                plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i]
            )
            actor = glyph_actor(v, f, colors, edges)
            self.glyph_actors.append(actor)
            self.renderer.AddActor(actor)

        self.viewpoint_panel.populate(plan)

        self.metrics_panel.set("Vertices", f"{len(mesh.vertices):,}")
        self.metrics_panel.set("Triangles", f"{len(mesh.faces):,}")
        self.metrics_panel.set("Diagonal", f"{self.diagonal:.2f}")
        self.metrics_panel.set("Targets", f"{len(data.targets):,}")
        self.metrics_panel.set("Cameras", f"{len(plan.positions):,}")

        self.renderer.ResetCamera()
        self.show_overview()
        self.set_mode(self.mode)
        self.statusBar().showMessage("Ready", 3000)

    # ------------------------------------------------------------------
    # display state
    # ------------------------------------------------------------------

    def set_mode(self, mode):
        self.mode = mode
        if self.mesh_actor is None:
            return

        prop = self.mesh_actor.GetProperty()
        mapper = self.mesh_actor.GetMapper()

        show_mesh = mode in (MODE_TEXTURED, MODE_GEOMETRY, MODE_ALL)
        show_cloud = mode in (MODE_TARGETS, MODE_ALL)

        self.mesh_actor.SetVisibility(show_mesh)
        self.cloud_actor.SetVisibility(show_cloud)
        if self.scalar_bar is not None:
            self.scalar_bar.SetVisibility(show_cloud)

        if mode == MODE_GEOMETRY:
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

        self.render()

    def set_scalar_field(self, field):
        if self.data is None or self.data.scores is None:
            return
        values = np.ascontiguousarray(getattr(self.data.scores, field), dtype=np.float32)

        arr = vtknp.numpy_to_vtk(values, deep=True)
        arr.SetName(field)
        self.cloud_polydata.GetPointData().SetScalars(arr)

        mapper = self.cloud_actor.GetMapper()
        mapper.SetScalarRange(float(values.min()), float(values.max()))
        mapper.ScalarVisibilityOn()

        if self.scalar_bar is not None:
            self.scalar_bar.SetTitle(field)

        self.metrics_panel.set("Field", field)
        self.metrics_panel.set("Min", f"{values.min():.4f}")
        self.metrics_panel.set("Mean", f"{values.mean():.4f}")
        self.metrics_panel.set("Max", f"{values.max():.4f}")
        self.render()

    def set_point_size(self, size):
        if self.cloud_actor is not None:
            self.cloud_actor.GetProperty().SetPointSize(float(size))
            self.render()

    def set_glyphs_visible(self, visible):
        self.show_glyphs = visible
        self._refresh_glyphs()
        self.render()

    def _refresh_glyphs(self):
        for i, actor in enumerate(self.glyph_actors):
            # Never draw the frustum you are sitting inside; it fills the view.
            actor.SetVisibility(self.show_glyphs and i != self.camera_index)

    # ------------------------------------------------------------------
    # camera flipping
    # ------------------------------------------------------------------

    def _save_overview(self):
        cam = self.renderer.GetActiveCamera()
        self.overview_state = (
            cam.GetPosition(), cam.GetFocalPoint(), cam.GetViewUp(), cam.GetViewAngle()
        )

    def show_overview(self):
        if self.overview_state is not None:
            cam = self.renderer.GetActiveCamera()
            pos, focal, up, angle = self.overview_state
            cam.SetPosition(*pos)
            cam.SetFocalPoint(*focal)
            cam.SetViewUp(*up)
            cam.SetViewAngle(angle)
            self.renderer.ResetCameraClippingRange()
        else:
            self._save_overview()

        self.camera_index = None
        self._refresh_glyphs()
        self.viewpoint_panel.select_row(None)

        for key in ("Camera", "Position", "Yaw", "Pitch"):
            self.metrics_panel.set(key, "--")
        self.statusBar().showMessage("Overview")
        self.render()

    def show_camera(self, index):
        if self.data is None:
            return
        plan = self.data.plan
        n = len(plan.positions)
        if n == 0:
            return

        if self.camera_index is None:
            self._save_overview()

        self.camera_index = index % n
        i = self.camera_index

        pose = vc.camera_pose(plan.positions[i], plan.yaws_deg[i], plan.pitches_deg[i])
        apply_pose(self.renderer.GetActiveCamera(), pose, YFOV_DEG, self.diagonal)

        self._refresh_glyphs()
        self.viewpoint_panel.select_row(i)

        pos = np.asarray(plan.positions[i], dtype=float)
        self.metrics_panel.set("Camera", f"{i + 1} of {n}")
        self.metrics_panel.set("Position", f"{pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}")
        self.metrics_panel.set("Yaw", f"{float(plan.yaws_deg[i]):.2f}")
        self.metrics_panel.set("Pitch", f"{float(plan.pitches_deg[i]):.2f}")
        self.statusBar().showMessage(f"Camera {i + 1} of {n}")
        self.render()

    def next_camera(self):
        self.show_camera(0 if self.camera_index is None else self.camera_index + 1)

    def prev_camera(self):
        self.show_camera(-1 if self.camera_index is None else self.camera_index - 1)

    # ------------------------------------------------------------------

    def render(self):
        self.vtk_widget.GetRenderWindow().Render()

    def _restore_layout(self):
        settings = QSettings("ViewScope", "viewer")
        geometry = settings.value("geometry")
        state = settings.value("state")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def closeEvent(self, event):
        settings = QSettings("ViewScope", "viewer")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())

        if self.loader.isRunning():
            self.loader.wait(2000)
        # Release the GL context explicitly; skipping this crashes on macOS.
        self.vtk_widget.Finalize()
        super().closeEvent(event)


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    app.setApplicationName("ViewScope")
    window.interactor.Initialize()
    app.exec()


if __name__ == "__main__":
    main()