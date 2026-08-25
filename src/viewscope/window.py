"""The application shell: docks, actions, and the wiring between them.

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

from .CameraFlippingPanel import CameraFlippingPanel
from .CameraViewport import CameraViewport
from .config import APP_NAME, DATA_DIR, MODES, ORG_NAME
from .DisplayPanel import DisplayPanel
from .loading import SceneData, SceneLoader
from .MetricsPanel import MetricsPanel
from .viewport import Viewport


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path = DATA_DIR):
        super().__init__()
        self.setWindowTitle("ViewScope")
        self.resize(1500, 950)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)  # set the cental widget vtk

        self.display_panel = DisplayPanel()
        self.metrics_panel = MetricsPanel()
        self.viewpoint_panel_choice = CameraFlippingPanel()

        self.camera_viewport = CameraViewport(self)

        # self.sector_panel =

        self.docks = {}
        self._add_dock(
            "Viewpoints",
            self.viewpoint_panel_choice,
            Qt.DockWidgetArea.LeftDockWidgetArea,
        )
        self._add_dock(
            "Display", self.display_panel, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._add_dock(
            "Camera View", self.camera_viewport, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._add_dock(
            "Metrics", self.metrics_panel, Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._connect()
        self._build_actions()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Loading...")
        self._restore_layout()

        self.loader = SceneLoader(data_dir, self)
        self.loader.progress.connect(self.statusBar().showMessage)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_failed)
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
        # self.display_panel.glyphs_toggled.connect(self.viewport.set_glyphs_visible)
        self.display_panel.field_changed.connect(self._on_field_changed)

        # self.viewpoint_panel_choice.camera_picked.connect(self.viewport.show_camera)
        # self.viewport.camera_changed.connect(self._on_camera_changed)

        self.display_panel.mode_changed.connect(self.camera_viewport.set_mode)
        self.display_panel.point_size_changed.connect(
            self.camera_viewport.set_point_size
        )
        self.display_panel.glyphs_toggled.connect(
            self.camera_viewport.set_glyphs_visible
        )
        self.display_panel.field_changed.connect(self._on_field_changed)

        self.viewpoint_panel_choice.camera_picked.connect(
            self.camera_viewport.show_camera
        )
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

        camera_actions = (self.act_prev, self.act_next, self.act_overview)
        for act in camera_actions:
            toolbar.addAction(act)
            self.addAction(act)  # keeps shortcuts alive when VTK has focus

        view_menu = self.menuBar().addMenu("&View")
        for dock in self.docks.values():
            view_menu.addAction(dock.toggleViewAction())

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
        QMessageBox.critical(
            self, "ViewScope", f"Could not load the bundle.\n\n{message}"
        )

    def _on_loaded(self, data: SceneData):
        self.viewport.set_scene(data)
        self.camera_viewport.set_scene(data)
        self.viewpoint_panel_choice.populate(data.plan)
        self.metrics_panel.show_bundle(data)

        if data.has_scores:
            self._on_field_changed(self.display_panel.field.currentText())
        else:
            self.display_panel.disable_fields()
            self.metrics_panel.show_field(None)
            if data.scores_error:
                print(f"scores unavailable: {data.scores_error}")

        self.viewport.show_overview()
        self.camera_viewport.show_overview()
        self.statusBar().showMessage("Ready", 3000)

    def _on_field_changed(self, field):
        self.metrics_panel.show_field(self.viewport.set_scalar_field(field))

        self.metrics_panel.show_field(self.camera_viewport.set_scalar_field(field))

    def _on_camera_changed(
        self, info
    ):  # info, see on_seletion in CameraFlippingPanel.py
        self.metrics_panel.show_camera(info)
        self.viewpoint_panel_choice.select_row(None if info is None else info.index)
        self.statusBar().showMessage(
            "Overview" if info is None else f"Camera {info.index + 1} of {info.count}"
        )

    # -- layout persistence --------------------------------------------

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
        if self.loader.isRunning():
            self.loader.wait(2000)
        self.viewport.shutdown()
        self.camera_viewport.shutdown()
        super().closeEvent(event)
