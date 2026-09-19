"""
ViewpointsPanel

This panel does not communicate with viewport.py directly
See _on_camera_changed in window.py
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from viewscope.data.store import SCENE_STORE
from viewscope.dialogs.addcamera_dialog import AddCameraDialog


class ViewpointsPanel(QWidget):
    """One row per planned camera; selecting a row jumps the viewport."""

    camera_picked = Signal(int)

    def __init__(self):
        super().__init__()

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Position", "Yaw", "Pitch"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self._suppress = False

        # Add new camera button
        self.add_camera_button = QPushButton("Add Camera")
        self.add_camera_button.clicked.connect(self._on_button_add_camera_clicked)

        # Duplicate camera button
        self.duplicate_camera_button = QPushButton("Duplicate Camera")
        self.duplicate_camera_button.clicked.connect(self._on_button_duplicate_camera_clicked)
        self.duplicate_camera_button.setEnabled(False)  # Only enabled when a camera is selected

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_camera_button)
        button_layout.addWidget(self.duplicate_camera_button)
        layout.addLayout(button_layout)

        # Call refresh() whenever the plan is changed (e.g, if a camera is added)
        SCENE_STORE.plan_changed.connect(self.refresh)

    def refresh(self):
        """Refresh the viewpoints table from the current scene."""
        if SCENE_STORE.scene is None:
            self._suppress = True
            try:
                self.table.setRowCount(0)
            finally:
                self._suppress = False

            return

        plan = SCENE_STORE.scene.plan
        print(f"Refreshing viewpoints table: {len(plan.ids)} cameras.")

        self._suppress = True
        try:
            n = len(plan.ids)
            self.table.setRowCount(n)

            for i in range(n):
                pos = np.asarray(plan.positions[i], dtype=float)

                values = [
                    plan.ids[i],
                    f"{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}",
                    f"{float(plan.yaws_deg[i]):.1f}",
                    f"{float(plan.pitches_deg[i]):.1f}",
                ]

                for col, text in enumerate(values):
                    self.table.setItem(i, col, QTableWidgetItem(text))

            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        finally:
            self._suppress = False

    def _on_selection(self):
        if self._suppress:
            return

        rows = self.table.selectionModel().selectedRows()
        self.duplicate_camera_button.setEnabled(bool(rows))
        if rows:
            self.camera_picked.emit(rows[0].row())

    def select_row(self, index: int | None):
        """Reflect a selection made elsewhere without re-emitting."""
        self._suppress = True

        self.duplicate_camera_button.setEnabled(index is not None)
        if index is None:
            self.table.clearSelection()
        else:
            self.table.selectRow(index)

        self._suppress = False

    def _on_button_add_camera_clicked(self):
        if SCENE_STORE.scene is None:
            return

        dialog = AddCameraDialog(title=self.add_camera_button.text(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        x, y, z, yaw, pitch = dialog.values()
        position = (x, y, z)

        SCENE_STORE.add_camera(position, yaw, pitch)
        print(f"Adding camera: position={position}, yaw={yaw}, pitch={pitch}.")

    def _on_button_duplicate_camera_clicked(self):
        if SCENE_STORE.scene is None:
            return

        # INVARIANT: This button is only enabled when a camera is selected,
        #            it should be impossible to reach this point without a selection.
        rows = self.table.selectionModel().selectedRows()
        assert rows

        index = rows[0].row()
        plan = SCENE_STORE.scene.plan

        current_position = tuple(np.asarray(plan.positions[index], dtype=float).tolist())
        current_yaw = float(plan.yaws_deg[index])
        current_pitch = float(plan.pitches_deg[index])

        dialog = AddCameraDialog(
            position=current_position,
            yaw=current_yaw,
            pitch=current_pitch,
            title=self.duplicate_camera_button.text(),
            parent=self,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        x, y, z, yaw, pitch = dialog.values()
        position = (x, y, z)

        SCENE_STORE.add_camera(position, yaw, pitch)
        print(f"Duplicating camera: position={position}, yaw={yaw}, pitch={pitch}.")
