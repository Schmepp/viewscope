"""

Display panel. this is the top right panel
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .config import MODE_ALL, MODES, SCALAR_FIELDS


class DisplayPanel(QWidget):
    """Display mode, scalar field, point size, glyph visibility."""

    mode_changed = Signal(str)
    field_changed = Signal(str)
    point_size_changed = Signal(int)
    glyphs_toggled = Signal(bool)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        box = QGroupBox("Scene")
        form = QFormLayout(box)

        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.setCurrentText(MODE_ALL)
        self.mode.currentTextChanged.connect(self.mode_changed)
        form.addRow("Display", self.mode)

        self.field = QComboBox()
        self.field.addItems(SCALAR_FIELDS)
        self.field.currentTextChanged.connect(self.field_changed)
        form.addRow("Colour by", self.field)

        self.point_size = QSlider(Qt.Orientation.Horizontal)
        self.point_size.setRange(1, 10)
        self.point_size.setValue(2)
        self.point_size.valueChanged.connect(self.point_size_changed)
        form.addRow("Point size", self.point_size)

        self.glyphs = QCheckBox("Show camera frusta")
        self.glyphs.setChecked(True)
        self.glyphs.toggled.connect(self.glyphs_toggled)
        form.addRow(self.glyphs)

        layout.addWidget(box)
        layout.addStretch(1)

    def disable_fields(self):
        self.field.setEnabled(False)
