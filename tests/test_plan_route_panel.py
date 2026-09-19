"""Unit tests for src/viewscope/panels/plan_route_panel.py.

The panel end of the route: it reports what was pressed and shows what it is
told, and does neither the planning nor the writing itself. That split is what
is checked here.
"""

import pytest
from PySide6.QtWidgets import QApplication

from viewscope.data.route import RouteStatus
from viewscope.panels.plan_route_panel import PlanRoutePanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    return PlanRoutePanel()


@pytest.fixture
def status():
    return RouteStatus(
        planning=True,
        selected=(0, 1),
        labels=("vp000", "vp001"),
        camera_count=4,
        observed=10,
        targets=100,
        sectors=(1, 0, 0, 1, 0, 0, 0, 0),
    )


# -----------------------------------------------------------------------------
# Generating a report
# -----------------------------------------------------------------------------


def test_the_report_button_sits_under_the_flight_path(panel):
    """It is a document about the path, so it belongs with the path."""
    box = panel.path_button.parent()

    assert panel.report_button.parent() is box


def test_pressing_it_is_asked_for_and_not_done_here(panel, status):
    """The panel has no scene and no path: all it can do is say this is wanted."""
    panel.show_route(status)
    asked = []
    panel.report_requested.connect(lambda: asked.append(True))

    panel.report_button.click()

    assert asked == [True]


def test_a_report_needs_a_scene_and_nothing_more(panel, status):
    """Not a route: the path falls back to the plan, and so does the report."""
    panel.show_route(None)
    assert not panel.report_button.isEnabled()

    panel.show_route(status)
    assert panel.report_button.isEnabled()


def test_a_report_can_be_asked_for_without_planning_a_route(panel, status):
    panel.show_route(
        RouteStatus(
            planning=False,
            selected=(),
            labels=(),
            camera_count=4,
            observed=0,
            targets=100,
            sectors=(0,) * 8,
        )
    )

    assert panel.report_button.isEnabled()


def test_where_the_report_went_is_shown(panel):
    panel.show_report("/tmp/route_report.pdf")

    assert "route_report.pdf" in panel.report_note.text()


def test_another_bundle_clears_the_line(panel):
    """The report belongs to the route it was written of, not to the panel."""
    panel.show_report("/tmp/route_report.pdf")

    panel.show_route(None)

    assert panel.report_note.text() == ""
