"""
The viewpoints table.

The panel never talks to the viewport directly -- MainWindow routes its
`camera_picked` signal. The `_suppress` flag is the part worth pinning: it
keeps a programmatic refresh or selection from looping back out as user intent.
"""

from __future__ import annotations

import pytest

from viewscope.panels.viewpoints_panel import ViewpointsPanel


@pytest.fixture
def panel(qapp, loaded_store):
    widget = ViewpointsPanel()
    widget.refresh()
    return widget


# -- Filling the table -------------------------------------------------


def test_the_table_has_a_row_per_camera(panel, sample_plan):
    assert panel.table.rowCount() == len(sample_plan.ids)
    assert panel.table.columnCount() == 4


def test_the_columns_are_labelled(panel):
    headers = [panel.table.horizontalHeaderItem(i).text() for i in range(4)]

    assert headers == ["#", "Position", "Yaw", "Pitch"]


def test_a_row_shows_the_planned_pose(panel):
    assert panel.table.item(0, 0).text() == "vp1"
    assert panel.table.item(0, 1).text() == "3.0, 0.0, 0.0"
    assert panel.table.item(0, 2).text() == "180.0"
    assert panel.table.item(0, 3).text() == "0.0"


def test_refreshing_without_a_scene_empties_the_table(qapp):
    panel = ViewpointsPanel()

    panel.refresh()

    assert panel.table.rowCount() == 0


def test_the_table_is_read_only(panel):
    """Editing a cell would silently diverge from the plan."""
    from PySide6.QtWidgets import QAbstractItemView

    assert panel.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers


# -- Picking a viewpoint -----------------------------------------------


def test_selecting_a_row_announces_the_camera(panel, spy):
    watcher = spy(panel.camera_picked)

    panel.table.selectRow(1)

    assert watcher.count == 1
    assert watcher.last == 1


def test_selecting_the_same_row_twice_announces_once(panel, spy):
    panel.table.selectRow(1)
    watcher = spy(panel.camera_picked)

    panel.table.selectRow(1)

    assert watcher.count == 0


def test_only_one_row_can_be_selected(panel):
    from PySide6.QtWidgets import QAbstractItemView

    assert panel.table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection


# -- Reflecting a selection made elsewhere -----------------------------


def test_select_row_highlights_without_announcing(panel, spy):
    """
    MainWindow calls this after the viewport moves. Re-emitting here would
    send the viewport straight back where it came from.
    """
    watcher = spy(panel.camera_picked)

    panel.select_row(1)

    assert watcher.count == 0
    assert panel.table.selectionModel().selectedRows()[0].row() == 1


def test_select_row_with_none_clears_the_highlight(panel, spy):
    panel.select_row(1)
    watcher = spy(panel.camera_picked)

    panel.select_row(None)

    assert panel.table.selectionModel().selectedRows() == []
    assert watcher.count == 0


def test_the_panel_still_responds_to_the_user_after_a_programmatic_select(panel, spy):
    """`_suppress` has to be cleared again, or picking stops working."""
    panel.select_row(1)
    watcher = spy(panel.camera_picked)

    panel.table.selectRow(0)

    assert watcher.count == 1
