"""

Camera flipping panel on left hand side
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox,
    QHeaderView, QLabel, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .config import MODE_ALL, MODES, SCALAR_FIELDS

class CameraFlippingPanel(QTableWidget):
    """One row per planned camera; selecting a row jumps the viewport."""

    camera_picked = Signal(int)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["#", "Position", "Yaw", "Pitch"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.itemSelectionChanged.connect(self._on_selection)
        self._suppress = False

    def populate(self, plan):
        self._suppress = True
        n = len(plan.positions)
        self.setRowCount(n)
        for i in range(n):
            pos = np.asarray(plan.positions[i], dtype=float)
            values = [
                str(i + 1),
                f"{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}",
                f"{float(plan.yaws_deg[i]):.1f}",
                f"{float(plan.pitches_deg[i]):.1f}",
            ]
            for col, text in enumerate(values):
                self.setItem(i, col, QTableWidgetItem(text))
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._suppress = False

    def _on_selection(self):
        if self._suppress:
            return
        rows = self.selectionModel().selectedRows()
        if rows:
            self.camera_picked.emit(rows[0].row())

    def select_row(self, index):
        """Reflect a selection made elsewhere without re-emitting."""
        self._suppress = True
        if index is None:
            self.clearSelection()
        else:
            self.selectRow(index)
        self._suppress = False