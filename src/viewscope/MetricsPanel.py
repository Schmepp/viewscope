"""Dockable panels.

Each panel reports user intent through signals and accepts state through
`show_*` methods. None of them touch VTK or the scene directly.



could potentially subdivide into separate panel classes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class MetricsPanel(QWidget):
    """Read-only figures about the bundle and the current viewpoint."""

    SECTIONS = (
        ("Bundle", ["Vertices", "Triangles", "Diagonal", "Targets", "Cameras"]),
        ("Scalar field", ["Field", "Min", "Mean", "Max"]),
        ("Viewpoint", ["Camera", "Position", "Yaw", "Pitch"]),
    )

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.rows = {}
        for title, keys in self.SECTIONS:
            box = QGroupBox(title)
            form = QFormLayout(box)
            for key in keys:
                label = QLabel("--")
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                form.addRow(key, label)
                self.rows[key] = label
            layout.addWidget(box)

        layout.addStretch(1)

    def set(self, key, value):
        if key in self.rows:
            self.rows[key].setText(str(value))

    def clear(self, keys):
        for key in keys:
            self.set(key, "--")

    def show_bundle(self, data):
        self.set("Vertices", f"{len(data.mesh.vertices):,}")
        self.set("Triangles", f"{len(data.mesh.faces):,}")
        self.set("Diagonal", f"{data.diagonal:.2f}")
        self.set("Targets", f"{len(data.targets):,}")
        self.set("Cameras", f"{data.camera_count:,}")

    def show_field(self, stats):
        if stats is None:
            self.set("Field", "unavailable")
            self.clear(["Min", "Mean", "Max"])
            return
        self.set("Field", stats.field)
        self.set("Min", f"{stats.minimum:.4f}")
        self.set("Mean", f"{stats.mean:.4f}")
        self.set("Max", f"{stats.maximum:.4f}")

    def show_camera(self, info):
        if info is None:
            self.clear(["Camera", "Position", "Yaw", "Pitch"])
            return
        pos = info.position
        self.set("Camera", f"{info.index + 1} of {info.count}")
        self.set("Position", f"{pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f}")
        self.set("Yaw", f"{info.yaw:.2f}")
        self.set("Pitch", f"{info.pitch:.2f}")
