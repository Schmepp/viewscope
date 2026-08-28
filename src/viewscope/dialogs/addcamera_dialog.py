from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)


class AddCameraDialog(QDialog):
    """Dialog for creating a new camera viewpoint."""

    # camera_created = Signal(float, float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Add Camera")

        # Position [x, y, z]
        self.position = [QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()]

        for widget in self.position:
            widget.setRange(-1_000_000.0, 1_000_000.0)
            widget.setDecimals(2)

        # Rotation
        self.yaw = QDoubleSpinBox()
        self.pitch = QDoubleSpinBox()

        self.yaw.setRange(-360.0, 360.0)
        self.pitch.setRange(-90.0, 90.0)

        self.yaw.setDecimals(1)
        self.pitch.setDecimals(1)

        self.form = QFormLayout()
        self.form.addRow("X:", self.position[0])
        self.form.addRow("Y:", self.position[1])
        self.form.addRow("Z:", self.position[2])
        self.form.addRow("Yaw:", self.yaw)
        self.form.addRow("Pitch:", self.pitch)

        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Cancel")
        self.reset_button = QPushButton("Reset")

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self._reset)

        buttons = QHBoxLayout()
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.reset_button)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addLayout(buttons)

    def values(self) -> tuple[float, float, float, float, float]:
        return (
            self.position[0].value(),
            self.position[1].value(),
            self.position[2].value(),
            self.yaw.value(),
            self.pitch.value(),
        )

    def _on_button_clicked(self, button: QPushButton):
        if button == self.reset_button:
            self._reset()

    def _reset(self):
        """Reset button logic."""
        for widget in self.position:
            widget.setValue(0.0)

        self.yaw.setValue(0.0)
        self.pitch.setValue(0.0)
