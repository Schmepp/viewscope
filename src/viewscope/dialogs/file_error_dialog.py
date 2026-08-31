from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, 
                               QVBoxLayout, QWidget, QLabel, QFileDialog,
                               QDialog, QHBoxLayout, QMessageBox)
from PySide6.QtCore import Qt, Signal
from viewscope import config
import sys
import os
from pathlib import Path

class FileErrorDialog(QDialog):

    def __init__(self, error_title, error_message, action_message, parent=None):
        super().__init__(parent)

        self.setWindowTitle("File Validation Failed")
        self.setMinimumWidth(500)
        self.setWindowModality(Qt.WindowModality.ApplicationModal) # Enforce modal standard, make it stay on top.

        layout = QVBoxLayout(self)

        self.setWindowTitle(str("Error: " + error_title))
        # Error message
        self.message = QLabel(error_message)
        layout.addWidget(self.message)

        # Actionable message
        self.action = QLabel(action_message)
        layout.addWidget(self.action)

        self.setLayout(layout)

        # Buttons
        self.open_folder_button = QPushButton("Open File Location")
        self.open_folder_button.clicked.connect(self.open_folder_location)

        self.exit_button = QPushButton("Exit Application")
        self.exit_button.clicked.connect(self.on_exit)

        layout.addWidget(self.open_folder_button)
        layout.addWidget(self.exit_button)

        self.selected_file = None

    def open_folder_location(self):
        folder_path = config.DATA_DIR
        os.startfile(folder_path)


    def on_exit(self):
        pass
        sys.exit("Error: Appropriate File wasn't selected.") 

