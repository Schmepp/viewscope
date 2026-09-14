# Unit tests for src/viewscope/startup.py

import os

# Must be set before Qt picks a platform plugin, so these run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from viewscope.config import Project  # noqa: E402
from viewscope.data.loader import STAGE_COUNT  # noqa: E402
from viewscope.startup import ProjectCard, StartupWindow  # noqa: E402

PROJECTS = (Project(name="Kiri Building", subtitle="A test bundle", data_dir="data/kiri"),)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app):
    window = StartupWindow(PROJECTS)
    yield window
    window.close()


def test_lists_every_project(page):
    """One card per project, named after it."""
    assert list(page.cards) == ["Kiri Building"]
    assert page.cards["Kiri Building"].project is PROJECTS[0]


def test_card_click_asks_for_its_project(app):
    card = ProjectCard(PROJECTS[0])
    picked = []
    card.clicked.connect(picked.append)

    card.activate()

    assert picked == [PROJECTS[0]]


def test_busy_card_ignores_further_clicks(app):
    card = ProjectCard(PROJECTS[0])
    picked = []
    card.clicked.connect(picked.append)

    card.set_busy(True)
    card.activate()

    assert picked == []
    assert card.property("busy") is True


def test_opening_shows_the_bar_and_marks_the_card_busy(page):
    """The viewer itself is built on the next event loop turn, which the test never runs."""
    page.open_project(PROJECTS[0])

    assert page.cards["Kiri Building"].property("busy") is True
    assert not page.bar.isHidden()
    assert page.bar.value() == 0
    assert page.bar.maximum() == STAGE_COUNT
    assert "Kiri Building" in page.status.text()


def test_stages_advance_the_bar(page):
    page.open_project(PROJECTS[0])

    page._on_stage(3, STAGE_COUNT)

    assert page.bar.value() == 3
    assert page.bar.maximum() == STAGE_COUNT


def test_failure_puts_the_page_back(page):
    page.open_project(PROJECTS[0])

    page._on_failed("no such bundle")

    assert page.viewer is None
    assert page.cards["Kiri Building"].property("busy") is False
    assert page.bar.isHidden()
    assert "try again" in page.status.text()
