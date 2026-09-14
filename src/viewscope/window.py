"""
The application shell: docks, actions, and the wiring between them.

This class deliberately holds no scene state. It routes panel signals into the
viewport and viewport signals back into the panels.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from viewscope.camera.structs import CameraInfo
from viewscope.CameraViewport import CameraViewport
from viewscope.config import APP_NAME, DATA_DIR, MODES, ORG_NAME
from viewscope.data.loader import SceneLoader
from viewscope.data.scene import SceneData
from viewscope.data.store import SCENE_STORE
from viewscope.dialogs.file_error_dialog import FileErrorDialog
from viewscope.DisplayPanel import DisplayPanel
from viewscope.MetricsPanel import MetricsPanel
from viewscope.panels.viewpoints_panel import ViewpointsPanel
from viewscope.scene.visibility import TargetVisibility
from viewscope.viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path = DATA_DIR):
        super().__init__()
        self.setWindowTitle("ViewScope")
        self.resize(1500, 950)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)  # set the cental widget vtk

        self.visibility = None  # TargetVisibility, once a scene is loaded
        self.selected_camera = None
        self.occlusion_on = False

        self.display_panel = DisplayPanel()
        self.metrics_panel = MetricsPanel()
        self.viewpoints_panel = ViewpointsPanel()
        self.camera_viewport = CameraViewport(self)

        self.docks = {}
        self._add_dock("Viewpoints", self.viewpoints_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Display", self.display_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Camera View", self.camera_viewport, Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Metrics", self.metrics_panel, Qt.DockWidgetArea.RightDockWidgetArea)

        self._connect()
        self._build_actions()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Loading...")

        # Snapshot the docks and toolbar as __init__ arranged them, before a
        # saved session overwrites them. This is what "Reset Layout" restores.
        self._default_state = self.saveState()
        self._restore_layout()

        # Load the scene
        self.loader = SceneLoader(data_dir, self)
        self.loader.progress.connect(self.statusBar().showMessage)
        self.loader.loaded.connect(self._on_scene_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.plan_validation_failed.connect(
            self.show_error_dialog
        )  # Connect file validation Dialog
        self.loader.filename_validation_failed.connect(self.show_error_dialog)
        self.loader.start()

    def start(self):
        """Hand control to the VTK interactor, once the window is visible."""
        self.viewport.start()
        self.camera_viewport.start()

    # -- construction --------------------------------------------------

    def _add_dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title}")  # required for saveState
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        self.docks[title] = dock
        return dock

    def _connect(self):
        self.display_panel.mode_changed.connect(self.viewport.set_mode)
        self.display_panel.point_size_changed.connect(self.viewport.set_point_size)
        self.display_panel.field_changed.connect(self._on_field_changed)
        self.display_panel.point_size_changed.connect(self.camera_viewport.set_point_size)
        self.display_panel.field_changed.connect(self._on_field_changed)
        self.display_panel.occlusion_toggled.connect(self._on_occlusion_toggled)
        self.display_panel.grid_toggled.connect(self.viewport.set_grid_visible)
        self.display_panel.glyphs_toggled.connect(self.viewport.set_glyphs_visible)

        # This updates the camera in FPV viewport
        # TODO(Adam): In future, I would prefer if camera_picked
        #             returned a CameraInfo and was wired into self._on_camera_changed.
        self.viewpoints_panel.camera_picked.connect(self.camera_viewport.show_camera)
        self.viewport.camera_picked.connect(self.camera_viewport.show_camera)
        self.viewport.camera_picked.connect(self.viewpoints_panel.select_row)

        SCENE_STORE.plan_changed.connect(self._on_plan_changed)
        self.camera_viewport.camera_changed.connect(self._on_camera_changed)

    def _build_actions(self):
        toolbar = self.addToolBar("Cameras")
        toolbar.setObjectName("toolbar_cameras")

        self.act_prev = QAction("Previous", self)
        self.act_prev.setShortcuts([QKeySequence("P"), QKeySequence(Qt.Key.Key_Left)])

        # self.act_prev.triggered.connect(self.viewport.prev_camera)

        self.act_next = QAction("Next", self)
        self.act_next.setShortcuts([QKeySequence("N"), QKeySequence(Qt.Key.Key_Right)])

        # self.act_next.triggered.connect(self.viewport.next_camera)

        self.act_overview = QAction("Overview", self)
        self.act_overview.setShortcut(QKeySequence("O"))
        self.act_overview.triggered.connect(self.viewport.show_overview)

        self.toggle_orientation = QAction("Toggle Orientation", self, checkable=True)
        self.toggle_orientation.triggered.connect(self.viewport.toggle_camera_orientation_visible)
        self.toggle_orientation.setChecked(True)

        camera_actions = (
            self.act_prev,
            self.act_next,
            self.act_overview,
            self.toggle_orientation,
        )
        for act in camera_actions:
            toolbar.addAction(act)
            self.addAction(act)  # keeps shortcuts alive when VTK has focus

        view_menu = self.menuBar().addMenu("&View")
        for dock in self.docks.values():
            view_menu.addAction(dock.toggleViewAction())

        view_menu.addSeparator()
        self.act_reset_layout = QAction("Reset Layout", self)
        self.act_reset_layout.triggered.connect(self.reset_layout)
        view_menu.addAction(self.act_reset_layout)

        camera_menu = self.menuBar().addMenu("&Camera")
        for act in camera_actions:
            camera_menu.addAction(act)

        # Number keys mirror the display combo box.
        for i, mode in enumerate(MODES, start=1):
            act = QAction(mode, self)
            act.setShortcut(QKeySequence(str(i)))
            act.triggered.connect(
                lambda _checked=False, m=mode: self.display_panel.mode.setCurrentText(m)
            )
            self.addAction(act)

        # -- camera ---

        self.act_prev.triggered.connect(self.camera_viewport.prev_camera)

        self.act_next.triggered.connect(self.camera_viewport.next_camera)

        self.act_overview.triggered.connect(self.camera_viewport.show_overview)

    # -- callbacks -----------------------------------------------------

    def _on_failed(self, message):
        self.statusBar().showMessage("Load failed")
        QMessageBox.critical(self, "ViewScope", f"Could not load the bundle.\n\n{message}")

    def _on_scene_loaded(self, scene: SceneData):
        SCENE_STORE.set_scene(scene)
        self.visibility = TargetVisibility(scene)

        self.viewport.set_scene(scene)
        self.camera_viewport.set_scene(scene)
        self.metrics_panel.show_bundle()

        if scene.has_scores:
            self._on_field_changed(self.display_panel.field.currentText())
        else:
            self.display_panel.disable_fields()
            self.metrics_panel.show_field(None)
            if scene.scores_error:
                print(f"scores unavailable: {scene.scores_error}")

        self.viewport.show_overview()
        self.camera_viewport.show_overview()
        self.statusBar().showMessage("Ready", 3000)

    def _on_field_changed(self, field):
        self.metrics_panel.show_field(self.viewport.set_scalar_field(field))
        self.metrics_panel.show_field(self.camera_viewport.set_scalar_field(field))

    def _on_camera_changed(self, info: CameraInfo | None):
        if SCENE_STORE.scene is None:
            return

        self.metrics_panel.show_camera(info)
        self.viewport.set_selected_camera_position(info)
        self.viewport.on_camera_changed()

        self.selected_camera = info
        if info is not None:
            self.viewpoints_panel.select_row(info.index)

        camera_count = SCENE_STORE.camera_count
        self.statusBar().showMessage(
            "Overview" if info is None else f"Camera {info.index + 1} of {camera_count}"
        )

        self._apply_occlusion()

    def _on_plan_changed(self, info: CameraInfo | None):
        if SCENE_STORE.scene is None:
            return

        self.viewport.on_plan_changed()

        self.selected_camera = info
        if info is not None:
            self.viewpoints_panel.select_row(info.index)

        camera_count = SCENE_STORE.camera_count
        self.statusBar().showMessage(
            "Overview" if info is None else f"Camera {info.index + 1} of {camera_count}"
        )

    # -- occlusion -----------------------------------------------------

    def _on_occlusion_toggled(self, enabled: bool):
        self.occlusion_on = enabled
        self._apply_occlusion()

    def _apply_occlusion(self):
        """Push the selected camera's visibility mask into both viewports."""
        mask = None

        if self.occlusion_on:
            if self.selected_camera is None:
                self.statusBar().showMessage("Pick a viewpoint to see what it can view", 4000)
            elif self.visibility is not None:
                try:
                    mask = self.visibility.mask_for(self.selected_camera.index)
                except Exception as exc:
                    self.statusBar().showMessage(f"Visibility failed: {exc}", 5000)

        self.viewport.set_occlusion_mask(mask)

        if mask is not None:
            seen = int(mask.sum())
            self.statusBar().showMessage(f"{seen} of {mask.size} targets visible", 5000)

    # -- layout persistence --------------------------------------------

    def reset_layout(self):
        """Put every dock and the toolbar back where the application starts them."""
        self.restoreState(self._default_state)
        self.statusBar().showMessage("Layout reset", 3000)

    def _restore_layout(self):
        settings = QSettings(ORG_NAME, APP_NAME)
        geometry = settings.value("geometry")
        state = settings.value("state")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        if isinstance(state, QByteArray):
            self.restoreState(state)

    def _save_layout(self):
        settings = QSettings(ORG_NAME, APP_NAME)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState())

    def closeEvent(self, event):
        self._save_layout()
        if self.visibility is not None:
            self.visibility.close()
        if self.loader.isRunning():
            self.loader.wait(2000)
        self.viewport.shutdown()
        self.camera_viewport.shutdown()
        super().closeEvent(event)

    # -- dialog window ---#
    def show_error_dialog(self, error_title, error_message, action_message):
        self.statusBar().showMessage("Plan validation failed")

        dialog = FileErrorDialog(
            error_title=error_title, error_message=error_message, action_message=action_message
        )
        dialog.exec()  # Use exec() instead of show() for modal dialog
