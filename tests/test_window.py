"""
The application shell.

MainWindow holds no scene state: it routes panel signals into the viewports
and viewport signals back into the panels. So the tests here are almost all
about wiring -- press a thing, check the other thing moved.

The real SceneLoader is a QThread that reads data/kiri off disk. It is stubbed
out, and `_on_scene_loaded` is called directly with the synthetic bundle, which
keeps these tests deterministic and off the filesystem.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt

from viewscope.config import APP_NAME, MODE_TARGETS, ORG_NAME
from viewscope.data.store import SCENE_STORE
from viewscope.window import MainWindow

pytestmark = pytest.mark.gl


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """
    Point QSettings at a scratch file.

    Without this the tests read and write the developer's real saved layout,
    and a restored dock arrangement changes what the assertions see.
    """
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path),
    )
    monkeypatch.setattr(QSettings, "__init__", _ini_settings_init(QSettings.__init__))
    yield tmp_path


def _ini_settings_init(original):
    def patched(self, *args, **kwargs):
        if args == (ORG_NAME, APP_NAME):
            original(
                self,
                QSettings.Format.IniFormat,
                QSettings.Scope.UserScope,
                ORG_NAME,
                APP_NAME,
            )
        else:
            original(self, *args, **kwargs)

    return patched


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, isolated_settings):
    """A MainWindow whose loader never runs."""
    monkeypatch.setattr("viewscope.data.loader.SceneLoader.start", lambda self: None)
    monkeypatch.setattr("viewscope.data.loader.SceneLoader.isRunning", lambda self: False)

    win = MainWindow(tmp_path)
    yield win

    for viewport in (win.viewport, win.camera_viewport):
        viewport.renderer.RemoveAllViewProps()
    win.viewport.orientation_widget.Off()
    win.viewport.orientation_widget.SetInteractor(None)
    win.viewport.orientation_widget.SetParentRenderer(None)
    win.close()


@pytest.fixture
def loaded_window(window, scored_scene_data):
    window._on_scene_loaded(scored_scene_data)
    return window


# -- Construction ------------------------------------------------------


def test_the_viewport_is_the_central_widget(window):
    assert window.centralWidget() is window.viewport


def test_every_dock_is_created(window):
    assert set(window.docks) == {"Viewpoints", "Display", "Camera View", "Metrics"}


def test_docks_are_named_so_the_layout_can_be_saved(window):
    """saveState() silently skips any dock without an object name."""
    for title, dock in window.docks.items():
        assert dock.objectName() == f"dock_{title}"


def test_the_camera_actions_exist(window):
    assert window.act_prev.text() == "Previous"
    assert window.act_next.text() == "Next"
    assert window.act_overview.text() == "Overview"


def test_the_shortcuts_survive_vtk_holding_focus(window):
    """
    The actions are added to the window as well as the toolbar. Without that,
    the keyboard stops working the moment the user clicks in the 3D view.
    """
    texts = [action.text() for action in window.actions()]

    for expected in ("Previous", "Next", "Overview"):
        assert expected in texts


def test_the_number_keys_mirror_the_display_combo(window):
    """1-4 pick a display mode; they are window actions, not toolbar ones."""
    from viewscope.config import MODES

    texts = [action.text() for action in window.actions()]

    for mode in MODES:
        assert mode in texts


def test_pressing_a_number_key_action_switches_mode(window):
    action = next(a for a in window.actions() if a.text() == MODE_TARGETS)

    action.trigger()

    assert window.display_panel.mode.currentText() == MODE_TARGETS


# -- Loading a scene ---------------------------------------------------


def test_loading_publishes_the_scene(loaded_window, scored_scene_data):
    assert SCENE_STORE.scene is scored_scene_data


def test_loading_fills_both_viewports(loaded_window):
    assert loaded_window.viewport.has_scene is True
    assert loaded_window.camera_viewport.has_scene is True


def test_loading_builds_the_visibility_helper(loaded_window):
    assert loaded_window.visibility is not None


def test_loading_fills_the_metrics_panel(loaded_window):
    assert loaded_window.metrics_panel.rows["Cameras"].text() == "2"
    assert loaded_window.metrics_panel.rows["Targets"].text() == "3"


def test_loading_shows_the_scalar_field(loaded_window):
    assert loaded_window.metrics_panel.rows["Field"].text() == "score_8"


def test_a_bundle_without_scores_disables_the_field_picker(window, scene_data):
    window._on_scene_loaded(scene_data)

    assert window.display_panel.field.isEnabled() is False
    assert window.metrics_panel.rows["Field"].text() == "unavailable"


def test_loading_reports_ready(loaded_window):
    assert loaded_window.statusBar().currentMessage() == "Ready"


def test_a_failed_load_says_so(window, monkeypatch):
    """The message box would block forever, so it is stubbed."""
    shown = []
    monkeypatch.setattr(
        "viewscope.window.QMessageBox.critical",
        lambda parent, title, text: shown.append(text),
    )

    window._on_failed("FileNotFoundError: scene.obj")

    assert window.statusBar().currentMessage() == "Load failed"
    assert "scene.obj" in shown[0]


# -- Panel to viewport wiring ------------------------------------------


def test_the_mode_combo_drives_both_viewports(loaded_window):
    loaded_window.display_panel.mode.setCurrentText(MODE_TARGETS)

    assert loaded_window.viewport.mesh.actor.GetVisibility() == 0
    assert loaded_window.camera_viewport.mesh.actor.GetVisibility() == 0


def test_the_point_size_slider_drives_both_viewports(loaded_window):
    loaded_window.display_panel.point_size.setValue(8)

    for viewport in (loaded_window.viewport, loaded_window.camera_viewport):
        assert viewport.cloud.actor.GetProperty().GetPointSize() == pytest.approx(8.0)


def test_the_glyph_checkbox_drives_the_preview(loaded_window):
    loaded_window.display_panel.glyphs.setChecked(False)

    assert all(a.GetVisibility() == 0 for a in loaded_window.camera_viewport.glyphs.actors)


def test_the_field_combo_updates_the_metrics(loaded_window):
    loaded_window.display_panel.field.setCurrentText("diversity_8")

    assert loaded_window.metrics_panel.rows["Field"].text() == "diversity_8"


def test_picking_a_viewpoint_flies_the_preview(loaded_window, sample_plan):
    loaded_window.viewpoints_panel.table.selectRow(1)

    assert np.allclose(
        loaded_window.camera_viewport.renderer.GetActiveCamera().GetPosition(),
        sample_plan.positions[1],
    )


# -- Viewport to panel wiring ------------------------------------------


def test_moving_the_camera_updates_the_status_bar(loaded_window):
    loaded_window.camera_viewport.show_camera(0)

    assert loaded_window.statusBar().currentMessage() == "Camera 1 of 2"


def test_returning_to_the_overview_says_so(loaded_window):
    loaded_window.camera_viewport.show_camera(0)

    loaded_window.camera_viewport.show_overview()

    assert loaded_window.statusBar().currentMessage() == "Overview"


def test_moving_the_camera_fills_the_metrics(loaded_window):
    loaded_window.camera_viewport.show_camera(1)

    assert loaded_window.metrics_panel.rows["Camera"].text() == "2 of 2"
    assert loaded_window.metrics_panel.rows["Yaw"].text() == "270.00"


def test_moving_the_camera_highlights_the_table_row(loaded_window):
    loaded_window.camera_viewport.show_camera(1)

    rows = loaded_window.viewpoints_panel.table.selectionModel().selectedRows()
    assert rows[0].row() == 1


def test_moving_the_camera_outlines_it_in_the_overview(loaded_window, sample_plan):
    loaded_window.camera_viewport.show_camera(0)

    outline = loaded_window.viewport.selected_outline.outline_actor
    assert outline is not None
    assert outline.GetCenter() == pytest.approx(tuple(sample_plan.positions[0]))


def test_camera_changes_before_a_scene_are_ignored(window):
    window._on_camera_changed(None)  # must not raise

    assert window.selected_camera is None


# -- Spawning a camera -------------------------------------------------


def test_spawning_a_camera_updates_everything(loaded_window, loaded_store):
    loaded_store.add_camera((1.0, 2.0, 3.0), yaw=45.0, pitch=-10.0)

    assert loaded_window.viewpoints_panel.table.rowCount() == 3
    assert loaded_window.metrics_panel.rows["Cameras"].text() == "3"
    assert len(loaded_window.viewport.glyphs.actors) == 3


# -- Occlusion ---------------------------------------------------------


def test_occlusion_without_a_selection_prompts_the_user(loaded_window):
    loaded_window.display_panel.occlusion.setChecked(True)

    assert "Pick a viewpoint" in loaded_window.statusBar().currentMessage()


def test_occlusion_paints_the_selected_camera(loaded_window):
    loaded_window.camera_viewport.show_camera(0)

    loaded_window.display_panel.occlusion.setChecked(True)

    assert loaded_window.viewport.cloud.occluding is True
    assert loaded_window.camera_viewport.cloud.occluding is True


def test_occlusion_counts_the_visible_targets(loaded_window):
    """The bundle's matrix says camera 0 sees two of the three targets."""
    loaded_window.camera_viewport.show_camera(0)

    loaded_window.display_panel.occlusion.setChecked(True)

    assert loaded_window.statusBar().currentMessage() == "2 of 3 targets visible"


def test_turning_occlusion_off_restores_the_field(loaded_window):
    loaded_window.camera_viewport.show_camera(0)
    loaded_window.display_panel.occlusion.setChecked(True)

    loaded_window.display_panel.occlusion.setChecked(False)

    assert loaded_window.viewport.cloud.occluding is False


def test_a_visibility_failure_is_reported_not_raised(loaded_window, monkeypatch):
    def explode(index):
        raise RuntimeError("no GL context")

    monkeypatch.setattr(loaded_window.visibility, "mask_for", explode)
    loaded_window.camera_viewport.show_camera(0)

    loaded_window.display_panel.occlusion.setChecked(True)

    assert "Visibility failed" in loaded_window.statusBar().currentMessage()


# -- Layout persistence ------------------------------------------------


def test_reset_layout_restores_the_starting_arrangement(window):
    window.removeDockWidget(window.docks["Metrics"])

    window.reset_layout()

    assert window.statusBar().currentMessage() == "Layout reset"


def test_the_layout_is_saved_on_close(window, isolated_settings):
    window._save_layout()

    settings = QSettings(ORG_NAME, APP_NAME)
    assert settings.value("state") is not None
    assert settings.value("geometry") is not None


def test_a_saved_layout_is_restored(window, isolated_settings):
    window.resizeDocks([window.docks["Metrics"]], [321], Qt.Orientation.Horizontal)
    window._save_layout()
    saved = QSettings(ORG_NAME, APP_NAME).value("state")

    window._restore_layout()

    assert QSettings(ORG_NAME, APP_NAME).value("state") == saved


# -- Error dialog ------------------------------------------------------


def test_a_validation_failure_opens_the_dialog(window, monkeypatch):
    """exec() would block the run, so the dialog is opened but not shown."""
    executed = []
    monkeypatch.setattr(
        "viewscope.window.FileErrorDialog.exec",
        lambda self: executed.append((self.windowTitle(), self.message.text())),
    )

    window.show_error_dialog("Bad plan", "only 10 viewpoints", "replace the file")

    assert executed == [("Bad plan", "only 10 viewpoints")]
    assert window.statusBar().currentMessage() == "Plan validation failed"
