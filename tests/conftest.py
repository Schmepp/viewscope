"""
Shared fixtures for the ViewScope test suite.

Two tiers of test run here:

* Headless tests build VTK actors, renderers and plain Qt widgets. These need
  no GPU and run anywhere, including under ``QT_QPA_PLATFORM=offscreen``.
* GL tests build the real ``Viewport`` widget, which is a
  ``QVTKRenderWindowInteractor`` and therefore needs a real OpenGL surface.
  They are marked ``@pytest.mark.gl`` and skip automatically when the Qt
  platform plugin cannot provide one.
"""

from __future__ import annotations

import os
import warnings

import numpy as np
import pytest
import trimesh
import vtk
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import viewscope_core as vc
from viewscope.data.scene import SceneData
from viewscope.data.store import SCENE_STORE

# Platform plugins that have no GL surface. Creating a QVTKRenderWindowInteractor
# under these segfaults rather than raising, so we skip instead of trying.
_HEADLESS_PLATFORMS = {"offscreen", "minimal", "vnc"}


def pytest_configure(config):
    config.addinivalue_line("markers", "gl: needs a real OpenGL surface (the VTK render window)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("QT_QPA_PLATFORM", "") not in _HEADLESS_PLATFORMS:
        return

    skip = pytest.mark.skip(reason="no OpenGL surface under QT_QPA_PLATFORM=offscreen")
    for item in items:
        if "gl" in item.keywords:
            item.add_marker(skip)


# -- Qt ----------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt does not allow a second."""
    app = QApplication.instance() or QApplication([])
    yield app


# -- Scene data --------------------------------------------------------


@pytest.fixture
def sample_mesh():
    """A 2x2x2 box, standing in for a loaded scan."""
    return trimesh.creation.box(extents=(2.0, 2.0, 2.0))


@pytest.fixture
def sample_plan():
    """Two planned viewpoints, facing the origin from +X and +Y."""
    return vc.Plan(
        camera={"width": 64, "height": 48, "yfov_deg": 53.1301},
        ids=("vp1", "vp2"),
        positions=np.array([[3.0, 0.0, 0.0], [0.0, 3.0, 0.0]]),
        yaws_deg=np.array([180.0, 270.0]),
        pitches_deg=np.array([0.0, 0.0]),
    )


@pytest.fixture
def scene_data(sample_mesh, sample_plan):
    """A minimal SceneData with no scores, built without touching data/."""
    return SceneData(
        mesh=sample_mesh,
        targets=np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        normals=np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        plan=sample_plan,
    )


@pytest.fixture
def sample_scores():
    """
    A vc.Scores covering the three targets, with every SCALAR_FIELDS entry.

    The numbers are arbitrary but distinct, so a test can tell which field the
    cloud is actually colouring by.
    """
    n = 3
    return vc.Scores(
        offsets=np.array([0, 1, 2, 3]),
        camera_index=np.array([0, 1, 0]),
        weight=np.ones(n),
        f_rho=np.ones(n),
        f_theta=np.ones(n),
        sector_8=np.zeros(n, dtype=np.int64),
        sector_4=np.zeros(n, dtype=np.int64),
        best_8=np.zeros(n),
        best_4=np.zeros(n),
        diversity_8=np.array([0.10, 0.20, 0.30]),
        diversity_4=np.array([0.15, 0.25, 0.35]),
        score_8=np.array([0.00, 0.50, 1.00]),
        score_4=np.array([0.25, 0.50, 0.75]),
        meta={},
    )


@pytest.fixture
def scored_scene_data(scene_data, sample_scores):
    """The same scene, but with scores, so the scalar-field paths are live."""
    scene_data.scores = sample_scores
    scene_data.visibility = np.array(
        [[True, False, True], [False, True, False]],
        dtype=bool,
    )
    return scene_data


@pytest.fixture(autouse=True)
def clean_scene_store():
    """
    SCENE_STORE is a module-level singleton, so state leaks between tests.

    Clear the scene and drop every signal connection afterwards: panels from a
    finished test are still connected, and firing a signal at a widget whose C++
    half has been deleted raises RuntimeError inside an unrelated test.
    """
    yield

    # Dropping every connection at once. signal.disconnect() warns when there
    # was nothing connected, so silence that rather than track each connection.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for signal in (
            SCENE_STORE.scene_loaded,
            SCENE_STORE.scene_unloaded,
            SCENE_STORE.scene_changed,
            SCENE_STORE.plan_changed,
        ):
            signal.disconnect()

    SCENE_STORE._scene = None


@pytest.fixture
def loaded_store(scene_data):
    """SCENE_STORE holding `scene_data`, the way MainWindow leaves it."""
    SCENE_STORE.set_scene(scene_data)
    return SCENE_STORE


# -- VTK ---------------------------------------------------------------


@pytest.fixture
def renderer():
    """
    A bare vtkRenderer, with no render window attached.

    Actors, cameras and mappers are all inspectable without a GL context; only
    Render() would need one, and nothing here calls it.
    """
    return vtk.vtkRenderer()


# -- The real widget ---------------------------------------------------


@pytest.fixture
def viewport(qapp):
    """The real Viewport widget. GL only -- use with @pytest.mark.gl."""
    from viewscope.viewport import Viewport

    widget = Viewport()
    yield widget

    # Teardown order matters. The camera orientation widget is a
    # vtkInteractorObserver holding the renderer and interactor; letting Python
    # garbage-collect it after the GL context is gone segfaults. Detach it
    # first, then release the context.
    widget.orientation_widget.Off()
    widget.orientation_widget.SetInteractor(None)
    widget.orientation_widget.SetParentRenderer(None)
    widget.renderer.RemoveAllViewProps()
    widget.shutdown()


@pytest.fixture
def loaded_viewport(viewport, scene_data, loaded_store):
    """A Viewport with `scene_data` already pushed in. GL only."""
    viewport.set_scene(scene_data)
    return viewport


@pytest.fixture
def fake_cursor(monkeypatch):
    """
    Stop the viewport warping the developer's real mouse pointer.

    viewport.py does `from PySide6.QtGui import QCursor`, so patching the name
    in that module is enough -- and is tidier than reaching into a Qt type.
    Returns the list of positions the viewport recentred the cursor to.
    """
    from viewscope import viewport as viewport_module

    positions: list[QPoint] = []

    class RecordingCursor:
        @staticmethod
        def setPos(point):
            positions.append(QPoint(point))

    monkeypatch.setattr(viewport_module, "QCursor", RecordingCursor)
    return positions


@pytest.fixture
def dragging_viewport(loaded_viewport, fake_cursor):
    """A started, sized viewport ready to receive synthetic mouse events."""
    loaded_viewport.resize(400, 300)
    loaded_viewport.start()
    return loaded_viewport


# -- Synthetic input ---------------------------------------------------


def mouse_press(x: float, y: float, button=Qt.MouseButton.LeftButton) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def mouse_move(x: float, y: float, buttons=Qt.MouseButton.LeftButton) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def mouse_release(
    x: float,
    y: float,
    button=Qt.MouseButton.LeftButton,
    still_held=Qt.MouseButton.NoButton,
) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(x, y),
        button,
        still_held,
        Qt.KeyboardModifier.NoModifier,
    )


# -- Helpers -----------------------------------------------------------


class SignalSpy:
    """Records every emission of a Qt signal, so tests can assert on them."""

    def __init__(self, signal):
        self.calls: list[tuple] = []
        signal.connect(lambda *args: self.calls.append(args))

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last(self):
        """The single argument of the most recent emission."""
        return self.calls[-1][0]


@pytest.fixture
def spy():
    return SignalSpy
