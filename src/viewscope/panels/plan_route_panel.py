"""
PlanRoutePanel

Choosing which of the planned viewpoints actually get flown. "Plan route"
puts every camera in and turns them blue in the 3D view; clicking a camera
there takes it out again, or puts it back. "Load route" starts from a route
saved earlier, or from another plan's json, instead of from the whole plan,
and hides every viewpoint that file did not name.
The coverage line answers the question the whole exercise is about: how many
targets the cameras still in the route can see between them.

Like the other panels it reports intent through signals and takes state
through `show_*`. It touches neither VTK nor the scene.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from viewscope.data.route import RouteStatus

IDLE_HINT = "Plan a route to choose which viewpoints get flown."
PLANNING_HINT = "Click a camera in the 3D view to take it out of the route, or put it back."


class PlanRoutePanel(QWidget):
    """The route: which cameras are in it, and what they see between them."""

    #: Start planning, with every camera in the route.
    plan_requested = Signal()
    #: Stop planning and write the route out.
    stop_requested = Signal()
    #: Plan a route from the viewpoints named by a json file the user picks.
    load_requested = Signal()
    select_all_requested = Signal()
    clear_requested = Signal()
    #: A row of the route list was chosen; jump to that camera.
    camera_picked = Signal(int)

    def __init__(self):
        super().__init__()

        self._selected: tuple[int, ...] = ()
        self._suppress = False

        layout = QVBoxLayout(self)

        self.hint = QLabel(IDLE_HINT)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        start = QHBoxLayout()
        self.plan_button = QPushButton("Plan route")
        self.plan_button.setToolTip("Put every viewpoint in the route and start choosing")
        self.plan_button.clicked.connect(self.plan_requested)
        start.addWidget(self.plan_button)

        self.load_button = QPushButton("Load route...")
        self.load_button.setToolTip(
            "Plan from a route or plan json, rather than from the viewpoints on show"
        )
        self.load_button.clicked.connect(self.load_requested)
        start.addWidget(self.load_button)
        layout.addLayout(start)

        layout.addWidget(self._build_summary())

        buttons = QHBoxLayout()
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(self.select_all_requested)
        buttons.addWidget(self.select_all_button)

        self.clear_button = QPushButton("Unselect all")
        self.clear_button.setToolTip("Take every camera out of the route")
        self.clear_button.clicked.connect(self.clear_requested)
        buttons.addWidget(self.clear_button)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("In the route"))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.list)

        self.stop_button = QPushButton("Stop planning")
        self.stop_button.setToolTip("Save the route to a JSON file and stop choosing")
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.show_route(None)

    # -- construction --------------------------------------------------

    def _build_summary(self) -> QGroupBox:
        box = QGroupBox("Route")
        form = QVBoxLayout(box)

        self.cameras = QLabel("--")
        self.coverage = QLabel("--")
        for label in (self.cameras, self.coverage):
            label.setWordWrap(True)
            form.addWidget(label)

        return box

    # -- state ---------------------------------------------------------

    def show_route(self, status: RouteStatus | None):
        """Fill the panel in, or empty it out when there is no scene."""
        planning = status is not None and status.planning

        self.hint.setText(PLANNING_HINT if planning else IDLE_HINT)
        self.plan_button.setEnabled(status is not None and not planning)
        # Loading is a way into planning and a way to start the route over
        # from a file, so it stays live either side of the switch.
        self.load_button.setEnabled(status is not None)
        for button in (self.select_all_button, self.clear_button, self.stop_button):
            button.setEnabled(planning)

        if status is None:
            self._selected = ()
            self.cameras.setText("--")
            self.coverage.setText("--")
            self._fill([])
            return

        self._selected = status.selected
        self.cameras.setText(f"Cameras: {len(status.selected)} of {status.camera_count} selected")
        self.coverage.setText(
            f"Targets observed: {status.observed:,} of {status.targets:,} ({status.coverage:.1%})"
        )
        self._fill(
            [
                f"{label}  (camera {index + 1})"
                for index, label in zip(status.selected, status.labels, strict=False)
            ]
        )

    def show_saved(self, path):
        """Say where the route went, or clear the line when given None."""
        self.note.setText("" if path is None else f"Saved to {path}")

    def show_loaded(self, path, added: int = 0):
        """Say which file the route came from, and what it brought with it."""
        appended = ""
        if added:
            appended = f", adding {added} viewpoint{'' if added == 1 else 's'} to the plan"
        self.note.setText(
            f"Loaded from {path}{appended}. Only its viewpoints are drawn; "
            "Select all puts the rest of the plan back on screen."
        )

    def select_camera(self, index: int | None):
        """Highlight one camera's row, without re-emitting."""
        self._suppress = True
        try:
            if index is None or index not in self._selected:
                self.list.clearSelection()
                return

            self.list.setCurrentRow(self._selected.index(index))
        finally:
            self._suppress = False

    # -- internals -----------------------------------------------------

    def _fill(self, rows: list[str]):
        self._suppress = True
        try:
            self.list.clear()
            for text in rows:
                self.list.addItem(QListWidgetItem(text))
        finally:
            self._suppress = False

    def _on_row_selected(self):
        if self._suppress:
            return

        row = self.list.currentRow()
        if 0 <= row < len(self._selected):
            self.camera_picked.emit(self._selected[row])
