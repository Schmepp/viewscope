"""Unit tests for stopping route planning in src/viewscope/window.py.

Stopping asks which of two things is meant: save the route, or leave planning
and keep nothing. Only the choosing is exercised here; building a whole window
would drag in VTK for no gain, so the method is run against a stand-in that
carries only the few things it touches.
"""

from pathlib import Path

import pytest

from viewscope.window import MainWindow


class Panel:
    """The one line of the panel stopping writes to."""

    def __init__(self):
        self.saved = "untouched"

    def show_saved(self, path):
        self.saved = path


class Route:
    """A route mid-planning, counting the calls that end it."""

    planning = True

    def __init__(self):
        self.stopped = 0
        self.writes = []

    def __len__(self):
        return 3

    def stop(self):
        self.stopped += 1
        self.planning = False

    def save(self, path, plan, observed, targets):
        self.writes.append(path)
        return path


class Bar:
    def __init__(self):
        self.messages = []

    def showMessage(self, text, _timeout=0):
        self.messages.append(text)


class Window:
    """Enough of a MainWindow for stop_route_planning to run against."""

    def __init__(self, choice, path=Path("route.json")):
        self.route = Route()
        self.route_mask = None
        self.plan_route_panel = Panel()
        self.bar = Bar()
        self.refreshes = 0
        self._choice = choice
        self._path = path
        self.asked_where = 0

    def statusBar(self):
        return self.bar

    def _refresh_route(self):
        self.refreshes += 1

    def _ask_stop_choice(self):
        return self._choice

    def _ask_route_path(self):
        self.asked_where += 1
        return self._path

    stop_route_planning = MainWindow.stop_route_planning


class Scene:
    plan = object()
    targets = ()


@pytest.fixture(autouse=True)
def scene(monkeypatch):
    """A loaded scene, which stopping needs before it will do anything."""

    class Store:
        scene = Scene()

    monkeypatch.setattr("viewscope.window.SCENE_STORE", Store())


# -----------------------------------------------------------------------------
# The two ways out
# -----------------------------------------------------------------------------


def test_saving_writes_the_route_and_leaves_planning():
    window = Window(choice=True)

    window.stop_route_planning()

    assert window.route.writes == [Path("route.json")]
    assert window.route.stopped == 1
    assert window.plan_route_panel.saved == Path("route.json")


def test_exiting_leaves_planning_and_writes_nothing():
    window = Window(choice=False)

    window.stop_route_planning()

    assert window.route.writes == []
    assert window.asked_where == 0, "exiting must not ask where to save"
    assert window.route.stopped == 1
    assert window.plan_route_panel.saved is None
    assert window.bar.messages == ["Left planning: the route was not saved"]


def test_exiting_still_repaints_the_scene():
    """The route colours are only worn while planning, so they must come off."""
    window = Window(choice=False)

    window.stop_route_planning()

    assert window.refreshes == 1


# -----------------------------------------------------------------------------
# Backing out
# -----------------------------------------------------------------------------


def test_closing_the_dialog_keeps_planning_on():
    window = Window(choice=None)

    window.stop_route_planning()

    assert window.route.planning
    assert window.route.stopped == 0
    assert window.plan_route_panel.saved == "untouched"


def test_backing_out_of_the_save_dialog_keeps_planning_on():
    window = Window(choice=True, path=None)

    window.stop_route_planning()

    assert window.route.planning
    assert window.route.writes == []
    assert window.bar.messages == ["Still planning: nothing was saved"]
