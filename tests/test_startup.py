# Unit tests for src/viewscope/startup.py

import os

# Must be set before Qt picks a platform plugin, so these run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from viewscope.config import Project  # noqa: E402
from viewscope.data.loader import STAGE_COUNT  # noqa: E402
from viewscope.dialogs.build_dialog import BuildBundleDialog  # noqa: E402
from viewscope.startup import (  # noqa: E402
    QUALITY_HIGH,
    QUALITY_LOW,
    QUALITY_MEDIUM,
    ProjectCard,
    StartupWindow,
    _Build,
)

PROJECTS = (Project(name="Kiri Building", subtitle="A test bundle", data_dir=Path("data/kiri")),)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    """A throwaway ini, so the tests never touch the real saved project list."""
    return QSettings(str(tmp_path / "viewscope.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def page(app, settings):
    window = StartupWindow(PROJECTS, settings=settings)
    yield window
    window.close()


def test_lists_every_project(page):
    """One card per project, keyed by the bundle it opens."""
    assert list(page.cards) == ["data/kiri"]
    assert page.cards["data/kiri"].project is PROJECTS[0]


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

    assert page.cards["data/kiri"].property("busy") is True
    assert not page.bar.isHidden()
    assert page.bar.value() == 0
    assert page.bar.maximum() == STAGE_COUNT
    assert "Kiri Building" in page.status.text()


def test_the_full_budget_is_the_default(page):
    """6G is picked when the page opens, so a project loads everything it ships."""
    assert page.quality_buttons[QUALITY_MEDIUM].isChecked()
    assert not page.quality_buttons[QUALITY_LOW].isChecked()
    assert not page.quality_buttons[QUALITY_HIGH].isChecked()
    assert page.load_photo_mesh is True
    assert page.full_resolution_mesh is False


def test_the_three_budgets_are_offered_in_order(page):
    """400MB, 6G, 10G, left to right in the corner."""
    assert list(page.quality_buttons) == [QUALITY_LOW, QUALITY_MEDIUM, QUALITY_HIGH]


def test_the_max_budget_reads_the_model_whole(page):
    """Picking 10G still loads the model, but uncapped and uncached."""
    page.quality_buttons[QUALITY_HIGH].click()

    assert page.load_photo_mesh is True
    assert page.full_resolution_mesh is True
    assert not page.quality_buttons[QUALITY_MEDIUM].isChecked()


def test_only_the_max_budget_asks_for_full_resolution(page):
    """The other two leave the loader on its capped, cached path."""
    for label in (QUALITY_LOW, QUALITY_MEDIUM):
        page.quality_buttons[label].click()
        assert page.full_resolution_mesh is False, label


def test_the_max_budget_still_has_a_second_phase(page):
    """10G reads the same model as 6G, so the bar switches over just the same."""
    page.quality_buttons[QUALITY_HIGH].click()
    page.open_project(PROJECTS[0])

    page._on_scene_loaded(None)

    assert page.bar.maximum() == 100
    assert "full-resolution" in page.status.text()


def test_the_light_budget_drops_the_full_resolution_model(page):
    """Picking 400MB unpicks 6G, and the viewer is told to stay on the simplified mesh."""
    page.quality_buttons[QUALITY_LOW].click()

    assert not page.quality_buttons[QUALITY_MEDIUM].isChecked()
    assert page.load_photo_mesh is False


def test_the_light_budget_leaves_the_bar_on_stages(page):
    """There is no second, full-resolution phase to switch the bar over to."""
    page.quality_buttons[QUALITY_LOW].click()
    page.open_project(PROJECTS[0])

    page._on_scene_loaded(None)

    assert page.bar.maximum() == STAGE_COUNT
    assert "full-resolution" not in page.status.text()


def test_the_full_budget_switches_the_bar_to_the_second_phase(page):
    page.open_project(PROJECTS[0])

    page._on_scene_loaded(None)

    assert page.bar.maximum() == 100
    assert "full-resolution" in page.status.text()


def test_the_budget_is_frozen_while_a_project_opens(page):
    """It is read once, when the project opens, so it must not be moved after that."""
    page.open_project(PROJECTS[0])
    assert not any(b.isEnabled() for b in page.quality_buttons.values())
    assert len(page.quality_buttons) == 3

    page._on_failed("no such bundle")
    assert all(b.isEnabled() for b in page.quality_buttons.values())


def test_stages_advance_the_bar(page):
    page.open_project(PROJECTS[0])

    page._on_stage(3, STAGE_COUNT)

    assert page.bar.value() == 3
    assert page.bar.maximum() == STAGE_COUNT


def test_failure_puts_the_page_back(page):
    page.open_project(PROJECTS[0])

    page._on_failed("no such bundle")

    assert page.viewer is None
    assert page.cards["data/kiri"].property("busy") is False
    assert page.bar.isHidden()
    assert "try again" in page.status.text()


# -- adding a project ------------------------------------------------------


def bundle(folder: Path) -> Path:
    """A folder holding the six files a bundle must have."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("scene.obj", "targets.ply", "plan.json", *NPZ_FILES):
        (folder / name).write_text("")
    return folder


NPZ_FILES = ("scores.npz", "visibility.npz", "flyable.npz")


def test_adding_a_complete_bundle(page, tmp_path):
    folder = bundle(tmp_path / "seahawk")

    assert page.add_folder(folder) is True
    assert str(folder) in page.cards
    assert page.projects[-1].name == "seahawk"
    assert "Added seahawk" in page.status.text()


def test_adding_an_incomplete_folder_is_refused(page, tmp_path):
    folder = tmp_path / "half"
    folder.mkdir()
    (folder / "scene.obj").write_text("")

    assert page.add_folder(folder) is False
    assert str(folder) not in page.cards
    assert "plan.json" in page.status.text()


def test_the_same_folder_is_not_added_twice(page, tmp_path):
    folder = bundle(tmp_path / "seahawk")
    page.add_folder(folder)

    assert page.add_folder(folder) is False
    assert len(page.cards) == 2  # the shipped one and the one added once


def test_added_projects_come_back_next_run(app, settings, tmp_path):
    folder = bundle(tmp_path / "seahawk")
    first = StartupWindow(PROJECTS, settings=settings)
    first.add_folder(folder)
    first.close()

    second = StartupWindow(PROJECTS, settings=settings)
    try:
        assert str(folder) in second.cards
        assert second.projects[-1].data_dir == folder
    finally:
        second.close()


def test_removing_an_added_project(page, tmp_path):
    folder = bundle(tmp_path / "seahawk")
    page.add_folder(folder)

    page.remove_project(page.projects[-1])

    assert str(folder) not in page.cards
    assert [p.name for p in page.projects] == ["Kiri Building"]

    # and it stays gone
    revisit = StartupWindow(PROJECTS, settings=page.settings)
    try:
        assert str(folder) not in revisit.cards
    finally:
        revisit.close()


def test_three_cards_keep_their_height_and_do_not_overlap(page, tmp_path):
    """A card that re-lays-out its own subtitle used to loop until the stack blew."""
    page.resize(880, 680)
    page.show()
    QApplication.processEvents()

    for index in range(2):
        page.add_folder(bundle(tmp_path / f"bundle{index}"))
    QApplication.processEvents()

    rows = [card.geometry() for card in page.cards.values()]
    assert [row.height() for row in rows] == [ProjectCard.HEIGHT] * 3
    for above, below in zip(rows, rows[1:], strict=False):  # consecutive pairs
        assert above.bottom() < below.top()


def test_a_long_subtitle_is_elided_into_the_card(page, tmp_path):
    folder = bundle(tmp_path / ("deeply/" * 12 + "nested"))
    page.resize(880, 680)
    page.show()
    page.add_folder(folder)
    QApplication.processEvents()

    card = page.cards[str(folder)]
    assert card.subtitle.text() != str(folder)  # shortened to fit
    assert "…" in card.subtitle.text()


# -- coming back, and building --------------------------------------------


def test_back_shows_the_page_and_resets_it(page):
    page.hide()
    page.status.setText("Ready")
    page.bar.show()
    next(iter(page.cards.values())).set_busy(True)

    page.show_projects()

    assert page.isVisible()
    assert page.viewer is None
    assert page.bar.isHidden()
    assert not next(iter(page.cards.values())).property("busy")
    assert "Select a project" in page.status.text()


def test_a_running_build_holds_off_opening(page):
    page.builder = object()  # stands in for the QProcess
    page._build = _Build(name="Seahawk", out_dir=Path("Seahawk"))

    page.open_project(PROJECTS[0])

    assert page.viewer is None
    assert not next(iter(page.cards.values())).property("busy")
    assert "Seahawk" in page.status.text()
    page.builder = None


def test_build_settings_come_from_the_dialog(app, tmp_path):
    model = tmp_path / "Seahawk.obj"
    model.write_text("")
    dialog = BuildBundleDialog(model)
    dialog.name.setText("Sea Hawk")
    dialog.length.setValue(19.76)
    dialog.up.setCurrentText("z")
    dialog.targets.setValue(12000)
    dialog.viewpoints.setValue(48)

    settings = dialog.settings()

    assert settings["name"] == "Sea Hawk"
    assert settings["out_dir"] == tmp_path  # beside the model, by default
    assert settings["length"] == 19.76
    assert settings["up"] == "z"
    assert (settings["targets"], settings["viewpoints"]) == (12000, 48)
    dialog.deleteLater()
