"""
The application shell: docks, actions, and the wiring between them.

This class deliberately holds no scene state. It routes panel signals into the
viewport and viewport signals back into the panels.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from viewscope.camera.structs import CameraInfo
from viewscope.CameraViewport import CameraViewport
from viewscope.config import APP_NAME, DATA_DIR, MODES, ORG_NAME, ROUTE_FILENAME
from viewscope.data.loader import SceneLoader
from viewscope.data.route import RoutePlan, load_route
from viewscope.data.scene import SceneData
from viewscope.data.store import SCENE_STORE
from viewscope.dialogs.file_error_dialog import FileErrorDialog
from viewscope.DisplayPanel import DisplayPanel
from viewscope.MetricsPanel import MetricsPanel
from viewscope.panels.plan_route_panel import PlanRoutePanel
from viewscope.panels.target_panel import TargetPanel
from viewscope.panels.viewpoints_panel import ViewpointsPanel
from viewscope.scene.target_report import TargetReport, TargetReports
from viewscope.scene.visibility import TargetVisibility
from viewscope.viewport import Viewport


class MainWindow(QMainWindow):
    #: Asked for the project list back. The startup screen is what answers it.
    back_requested = Signal()

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        *,
        expected_viewpoints: int | None = None,
        defer_load: bool = False,
    ):
        """
        Build the shell and, unless the load is deferred, start reading the bundle.

        expected_viewpoints is the plan size a shipped bundle is known to hold,
        checked while loading. Pass defer_load=True to leave the loader idle:
        the startup screen uses that to connect to its signals before the first
        one is emitted, then calls self.loader.start() itself.
        """
        super().__init__()
        self.setWindowTitle("ViewScope")
        self.resize(1500, 950)

        self.viewport = Viewport(self)
        self.setCentralWidget(self.viewport)  # Set the cental widget vtk

        self.visibility = None  # TargetVisibility, once a scene is loaded
        self.reports = None  # TargetReports, likewise
        self.route = RoutePlan()
        #: What the whole route can see, while planning is on. Recounted on
        #: every route change, because both the coverage line and the
        #: occlusion colouring read it.
        self.route_mask = None
        #: When a plan was loaded from a file, the viewpoint ids it named.
        #: Every camera in the scene whose id is not one of them is switched
        #: off, so the scene holds that plan and nothing else, until another
        #: is loaded or the whole plan is asked for back. None while every
        #: viewpoint is on show.
        self.route_shown: set[str] | None = None
        self.selected_camera = None
        self.selected_target: TargetReport | None = None
        self.occlusion_on = False

        self.camera_viewport = CameraViewport(self)
        self.display_panel = DisplayPanel()
        self.metrics_panel = MetricsPanel()
        self.viewpoints_panel = ViewpointsPanel()
        self.target_panel = TargetPanel()
        self.plan_route_panel = PlanRoutePanel()
        self.camera_viewport = CameraViewport(self)

        self.docks = {}
        self._add_dock("Viewpoints", self.viewpoints_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Target", self.target_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Plan Route", self.plan_route_panel, Qt.DockWidgetArea.LeftDockWidgetArea)
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
        self.loader = SceneLoader(data_dir, self, expected_viewpoints)
        self.loader.progress.connect(self.statusBar().showMessage)
        self.loader.loaded.connect(self._on_scene_loaded)
        self.loader.failed.connect(self._on_failed)
        self.loader.plan_validation_failed.connect(self.show_error_dialog)
        self.loader.filename_validation_failed.connect(self.show_error_dialog)
        if not defer_load:
            self.loader.start()

    def start(self):
        """Hand control to the VTK interactor, once the window is visible."""
        self.viewport.start()
        self.camera_viewport.start()

    # -- Construction --------------------------------------------------

    def _add_dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title}")  # Required for saveState
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        self.docks[title] = dock
        return dock

    def _connect(self):
        self.display_panel.mode_changed.connect(self.viewport.set_render_mode)
        self.display_panel.point_size_changed.connect(self.viewport.set_point_size)
        self.display_panel.field_changed.connect(self._on_field_changed)
        self.display_panel.field_changed.connect(self._on_field_changed)
        self.display_panel.occlusion_toggled.connect(self._on_occlusion_toggled)
        self.display_panel.grid_toggled.connect(self.viewport.set_grid_visible)
        self.display_panel.glyphs_toggled.connect(self.viewport.set_glyphs_visible)
        self.display_panel.glyph_wireframe_toggled.connect(self.viewport.toggle_glyph_wireframe)

        # This updates the camera in FPV viewport
        # TODO(Adam): In future, I would prefer if camera_picked
        #             returned a CameraInfo and was wired into self._on_camera_changed.
        self.viewpoints_panel.camera_picked.connect(self.camera_viewport.show_camera)
        self.viewport.camera_picked.connect(self.camera_viewport.show_camera)
        self.viewport.camera_picked.connect(self.viewpoints_panel.select_row)

        # Picking a target in the 3D view fills the target panel in; the
        # panel's own controls only ever change what is drawn for it.
        self.viewport.target_picked.connect(self._on_target_picked)
        self.viewport.target_cleared.connect(self.clear_target)
        self.target_panel.sector_count_changed.connect(self._on_sector_count_changed)
        self.target_panel.overlay_changed.connect(self._refresh_target_overlay)
        self.target_panel.cleared.connect(self.clear_target)
        self.target_panel.camera_picked.connect(self.camera_viewport.show_camera)
        self.target_panel.camera_picked.connect(self.viewpoints_panel.select_row)

        # While planning is on, clicking a camera in the 3D view takes it out
        # of the route or puts it back.
        self.viewport.camera_picked.connect(self._on_route_camera_picked)
        self.plan_route_panel.plan_requested.connect(self.start_route_planning)
        self.plan_route_panel.stop_requested.connect(self.stop_route_planning)
        self.plan_route_panel.load_requested.connect(self.load_route_file)
        self.plan_route_panel.select_all_requested.connect(self._on_route_select_all)
        self.plan_route_panel.clear_requested.connect(self._on_route_clear)
        self.plan_route_panel.camera_picked.connect(self.camera_viewport.show_camera)
        self.plan_route_panel.camera_picked.connect(self.viewpoints_panel.select_row)

        SCENE_STORE.plan_changed.connect(self._on_plan_changed)
        self.camera_viewport.camera_changed.connect(self._on_camera_changed)

    def _build_actions(self):
        project_bar = self.addToolBar("Project")
        project_bar.setObjectName("toolbar_project")

        self.act_back = QAction("\u2190 Projects", self)
        self.act_back.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.act_back.setToolTip("Close this bundle and pick another (Ctrl+Shift+P)")
        self.act_back.triggered.connect(self.back_requested)
        project_bar.addAction(self.act_back)
        self.addAction(self.act_back)  # keeps the shortcut alive when VTK has focus

        project_menu = self.menuBar().addMenu("&Project")
        project_menu.addAction(self.act_back)

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

        self.act_clear_target = QAction("Clear Target", self)
        self.act_clear_target.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.act_clear_target.setToolTip("Let go of the picked target (Esc)")
        self.act_clear_target.triggered.connect(self.clear_target)
        self.act_clear_target.setEnabled(False)

        self.toggle_orientation = QAction("Toggle Orientation", self, checkable=True)
        self.toggle_orientation.triggered.connect(self.viewport.toggle_camera_orientation_visible)
        self.toggle_orientation.setChecked(True)

        camera_actions = (
            self.act_prev,
            self.act_next,
            self.act_overview,
            self.act_clear_target,
            self.toggle_orientation,
        )
        for act in camera_actions:
            toolbar.addAction(act)
            self.addAction(act)  # Keeps shortcuts alive when VTK has focus

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
        self.reports = TargetReports(scene, self.visibility)

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

        self._refresh_route()

        self.viewport.show_overview()
        self.camera_viewport.show_overview()
        self.statusBar().showMessage("Ready", 3000)

    def _on_field_changed(self, field):
        self.metrics_panel.show_field(self.viewport.set_scalar_field(field))

    def _on_camera_changed(self, info: CameraInfo | None):
        if SCENE_STORE.scene is None:
            return

        self.metrics_panel.show_camera(info)
        self.viewport.on_camera_changed(info)

        self.selected_camera = info
        if info is not None:
            self.viewpoints_panel.select_row(info.index)
        self.target_panel.select_camera(None if info is None else info.index)
        self.plan_route_panel.select_camera(None if info is None else info.index)

        camera_count = SCENE_STORE.camera_count
        self.statusBar().showMessage(
            "Overview" if info is None else f"Camera {info.index + 1} of {camera_count}"
        )

        self._apply_occlusion()

    def _on_plan_changed(self, info: CameraInfo | None):
        if SCENE_STORE.scene is None:
            return

        self.viewport.on_plan_changed()

        # A new camera changes who observes what, so every cached report and
        # the overlay drawn from one are out of date.
        if self.reports is not None:
            self.reports.forget()
        self._rebuild_target()

        # on_plan_changed built fresh glyphs, which know nothing of the route.
        self.route.forget_beyond(SCENE_STORE.camera_count)
        self._refresh_route()

        self.selected_camera = info
        if info is not None:
            self.viewpoints_panel.select_row(info.index)

        camera_count = SCENE_STORE.camera_count
        self.statusBar().showMessage(
            "Overview" if info is None else f"Camera {info.index + 1} of {camera_count}"
        )

    # -- target inspection ---------------------------------------------

    def _on_target_picked(self, index: int):
        """Break down the target just clicked in the 3D view."""
        report = None if self.reports is None else self.reports.report(index, self.sector_count)

        if report is None:
            self.clear_target()
            return

        self.selected_target = report
        self.act_clear_target.setEnabled(True)
        self.target_panel.show_target(report)
        self.target_panel.select_camera(
            None if self.selected_camera is None else self.selected_camera.index
        )
        self._refresh_target_overlay()

        self.statusBar().showMessage(
            f"Target {report.index}: {len(report.observers)} observers across "
            f"{report.occupied_sectors} of {report.sector_count} sectors",
            6000,
        )

    def _on_sector_count_changed(self, _count: int):
        """The same target, cut into a different number of wedges."""
        self._rebuild_target()

    def clear_target(self):
        """Let go of the picked target, in the panel and in the view."""
        if self.selected_target is None:
            return

        self.selected_target = None
        self.act_clear_target.setEnabled(False)
        self.target_panel.show_target(None)
        self.viewport.clear_target_overlay()

    def _rebuild_target(self):
        """Re-read the selected target, for when the plan or the sectors move."""
        if self.selected_target is not None:
            self._on_target_picked(self.selected_target.index)

    def _refresh_target_overlay(self):
        """Redraw the overlay from the panel's current options."""
        if self.selected_target is None or SCENE_STORE.scene is None:
            self.viewport.clear_target_overlay()
            return

        self.viewport.show_target_overlay(
            self.selected_target,
            SCENE_STORE.scene.plan.positions,
            SCENE_STORE.scene.diagonal,
            self.target_panel.options(),
        )

    @property
    def sector_count(self) -> int:
        return self.target_panel.sector_count

    # -- route planning ------------------------------------------------

    def start_route_planning(self):
        """Put every viewpoint in the route and start choosing between them."""
        if SCENE_STORE.scene is None:
            return

        self.route.start(SCENE_STORE.camera_count)
        self.route_shown = None
        self.plan_route_panel.show_saved(None)
        self._refresh_route()
        self.statusBar().showMessage(
            "Planning a route: click a camera to take it out, or put it back", 6000
        )

    def load_route_file(self):
        """Plan the route named by a json file, instead of the plan on show.

        The file is read as a plan: a route saved earlier, or the plan.json of
        another bundle. Viewpoints it names that the current plan already has
        are matched by id and left where they are; the rest are appended, so a
        route planned against a different plan still arrives whole.
        """
        if SCENE_STORE.scene is None:
            return

        path = self._ask_loaded_route_path()
        if path is None:
            return

        try:
            entries = load_route(path)
        except ValueError as exc:
            QMessageBox.warning(self, "ViewScope", f"Could not load that route.\n\n{exc}")
            return

        rows, added = SCENE_STORE.ensure_cameras(
            [(entry.id, entry.position, entry.yaw_deg, entry.pitch_deg) for entry in entries]
        )

        self.route.select(rows)
        self.route.resume()
        # The file names the plan on show: every other camera in the scene is
        # switched off until the user asks for the rest back.
        self.route_shown = {entry.id for entry in entries}
        self._refresh_route()
        self.plan_route_panel.show_loaded(path, added)
        self.statusBar().showMessage(f"Planning the {len(rows)} viewpoints of {path.name}", 6000)

    def stop_route_planning(self):
        """Write the route out, then leave planning. Cancelling keeps planning on."""
        scene = SCENE_STORE.scene
        if scene is None or not self.route.planning:
            return

        path = self._ask_route_path()
        if path is None:
            self.statusBar().showMessage("Still planning: nothing was saved", 4000)
            return

        observed = 0 if self.route_mask is None else int(self.route_mask.sum())
        try:
            written = self.route.save(path, scene.plan, observed, len(scene.targets))
        except OSError as exc:
            QMessageBox.critical(self, "ViewScope", f"Could not save the route.\n\n{exc}")
            return

        self.route.stop()
        self._refresh_route()
        self.plan_route_panel.show_saved(written)
        self.statusBar().showMessage(f"Route saved to {written}", 6000)

    def _ask_route_path(self):
        """Where to write the route, or None if the user changed their mind."""
        suggested = Path(self.loader.data_dir) / ROUTE_FILENAME
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save route", str(suggested), "JSON (*.json)"
        )

        return Path(chosen) if chosen else None

    def _ask_loaded_route_path(self):
        """Which route to read, or None if the user changed their mind."""
        start = Path(self.loader.data_dir) / ROUTE_FILENAME
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Load route", str(start), "JSON (*.json)"
        )

        return Path(chosen) if chosen else None

    def _on_route_camera_picked(self, index: int):
        if not self.route.planning:
            return

        inside = self.route.toggle(index)
        self._refresh_route()

        plan = SCENE_STORE.scene.plan if SCENE_STORE.scene is not None else None
        name = plan.ids[index] if plan is not None and index < len(plan.ids) else f"#{index + 1}"
        self.statusBar().showMessage(
            f"{name} {'added to' if inside else 'taken out of'} the route", 4000
        )

    def _on_route_select_all(self):
        """Put the whole plan in the route, and back on the screen with it."""
        self.route.select_all(SCENE_STORE.camera_count)
        self.route_shown = None
        self._refresh_route()

    def _on_route_clear(self):
        self.route.clear()
        self._refresh_route()

    def _route_coverage(self):
        """The targets the route can see between them, or None when it sees none."""
        if self.visibility is None or not len(self.route):
            return None

        try:
            return self.visibility.union_mask(self.route.selected)
        except Exception as exc:
            self.statusBar().showMessage(f"Coverage unavailable: {exc}", 5000)
            return None

    def _refresh_route(self):
        """Repaint the glyphs and recount the coverage, after any route change."""
        scene = SCENE_STORE.scene
        if scene is None:
            self.plan_route_panel.show_route(None)
            return

        self.route_mask = self._route_coverage() if self.route.planning else None
        observed = 0 if self.route_mask is None else int(self.route_mask.sum())

        selected = set(self.route.selected)
        if self.route_shown is not None:
            # A camera put back into the route is drawn, whatever the file said.
            ids = scene.plan.ids
            self.route_shown |= {ids[i] for i in selected if i < len(ids)}

        # The route colours are only worn while planning, but a loaded plan
        # keeps the rest of the viewpoints off the screen either way: it is
        # the plan on show until another one is loaded.
        self.viewport.set_route_selection(
            selected if self.route.planning else None, self.route_shown
        )
        self.plan_route_panel.show_route(
            self.route.status(scene.plan, observed, len(scene.targets))
        )

        # Occlusion follows the route while planning, so every camera in it
        # paints at once rather than only the one last clicked.
        self._apply_occlusion()

    # -- occlusion -----------------------------------------------------

    def _on_occlusion_toggled(self, enabled: bool):
        self.occlusion_on = enabled
        self._apply_occlusion()

    def _apply_occlusion(self):
        """Push a visibility mask into the viewport.

        While a route is being planned that is everything the route sees
        between them, so taking a camera out shows what goes dark with it.
        Otherwise it is the one selected viewpoint.
        """
        mask = None
        planning = self.route.planning

        if self.occlusion_on:
            if planning:
                mask = self.route_mask
                if mask is None:
                    self.statusBar().showMessage("Put a camera in the route to see its cover", 4000)
            elif self.selected_camera is None:
                self.statusBar().showMessage("Pick a viewpoint to see what it can view", 4000)
            elif self.visibility is not None:
                try:
                    mask = self.visibility.mask_for(self.selected_camera.index)
                except Exception as exc:
                    self.statusBar().showMessage(f"Visibility failed: {exc}", 5000)

        self.viewport.set_occlusion_mask(mask)

        if mask is not None:
            seen = int(mask.sum())
            subject = (
                f"the {len(self.route)} cameras in the route" if planning else "this viewpoint"
            )
            self.statusBar().showMessage(
                f"{seen} of {mask.size} targets visible to {subject}", 5000
            )

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
        # Safe to run twice: closing the window and later destroying it both
        # come through here, and the things being released do not take it twice.
        self._save_layout()
        if self.visibility is not None:
            self.visibility.close()
            self.visibility = None
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
