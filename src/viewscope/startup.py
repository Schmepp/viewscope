"""
The startup screen: pick a project, watch it load, then hand over to the viewer.

Choosing a project builds a MainWindow immediately but keeps it hidden, so the
loading bar can follow the real bundle load instead of guessing at one. The
viewer only appears once its scene is on screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from viewscope import config
from viewscope import window as wd
from viewscope.config import Project
from viewscope.data.loader import STAGE_COUNT

STYLESHEET = f"""
#startupPage {{
    background: {config.IVORY};
}}
#title {{
    color: {config.INK};
}}
#tagline {{
    color: {config.MUTED};
    font-size: 13px;
    letter-spacing: 1px;
}}
#sectionLabel {{
    color: {config.MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
}}
#hairline {{
    background: {config.HAIRLINE};
    border: none;
}}
#projectCard {{
    background: {config.CARD};
    border: 1px solid {config.CARD_BORDER};
    border-radius: 10px;
}}
#projectCard:hover {{
    background: {config.CARD_HOVER};
    border-color: {config.CARD_BORDER_HOVER};
}}
#projectCard:focus {{
    border-color: {config.ACCENT};
}}
#projectCard[busy="true"] {{
    background: {config.TRACK};
    border-color: {config.CARD_BORDER};
}}
#cardMark {{
    background: {config.TRACK};
    color: {config.ACCENT};
    border-radius: 8px;
    font-size: 19px;
    font-weight: 600;
}}
#cardName {{
    color: {config.INK};
    font-size: 15px;
    font-weight: 600;
}}
#cardSubtitle {{
    color: {config.MUTED};
    font-size: 12px;
}}
#cardChevron {{
    color: {config.ACCENT};
    font-size: 17px;
}}
#status {{
    color: {config.MUTED};
    font-size: 12px;
}}
QProgressBar {{
    background: {config.TRACK};
    border: none;
    border-radius: 3px;
}}
QProgressBar::chunk {{
    background: {config.ACCENT};
    border-radius: 3px;
}}
"""


def wordmark_font() -> QFont:
    """A serif face for the title, whichever of these the platform has."""
    font = QFont()
    font.setFamilies(["Palatino", "Georgia", "Times New Roman"])
    font.setStyleHint(QFont.StyleHint.Serif)
    font.setPixelSize(58)
    font.setWeight(QFont.Weight.Medium)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
    return font


class ProjectCard(QFrame):
    """One project in the list. Clicking it, or pressing Return on it, opens it."""

    clicked = Signal(object)  # Project

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setObjectName("projectCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty("busy", False)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 20, 16)
        row.setSpacing(16)

        mark = QLabel(project.name[:1].upper())
        mark.setObjectName("cardMark")
        mark.setFixedSize(46, 46)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(mark)

        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(project.name)
        name.setObjectName("cardName")
        subtitle = QLabel(project.subtitle)
        subtitle.setObjectName("cardSubtitle")
        text.addWidget(name)
        text.addWidget(subtitle)
        row.addLayout(text, 1)

        self.chevron = QLabel("→")
        self.chevron.setObjectName("cardChevron")
        row.addWidget(self.chevron, 0, Qt.AlignmentFlag.AlignVCenter)

    # -- interaction ---------------------------------------------------

    def mouseReleaseEvent(self, event):
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self.activate()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activate()
            return
        super().keyPressEvent(event)

    def activate(self):
        """Ask for this project, unless it is already opening."""
        if not self.property("busy"):
            self.clicked.emit(self.project)

    def set_busy(self, busy: bool):
        self.setProperty("busy", busy)
        self.chevron.setText("…" if busy else "→")
        self.setCursor(Qt.CursorShape.ArrowCursor if busy else Qt.CursorShape.PointingHandCursor)
        # Qt only re-reads property selectors when the style is refreshed.
        self.style().unpolish(self)
        self.style().polish(self)


class StartupWindow(QWidget):
    """Ivory landing page: the wordmark above, the project list below."""

    def __init__(self, projects=config.PROJECTS, parent=None):
        super().__init__(parent)
        self.setObjectName("startupPage")
        self.setWindowTitle("Swapchain")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(680, 520)
        self.resize(880, 620)

        self.viewer = None  # the MainWindow being loaded, once a project is picked

        page = QVBoxLayout(self)
        page.setContentsMargins(56, 48, 56, 40)
        page.setSpacing(0)

        title = QLabel("Swapchain")
        title.setObjectName("title")
        title.setFont(wordmark_font())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        tagline = QLabel("VIEWPOINT PLANNING STUDIO")
        tagline.setObjectName("tagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)

        page.addStretch(3)
        page.addWidget(title)
        page.addSpacing(12)
        page.addWidget(tagline)
        page.addStretch(4)

        page.addLayout(self._section_heading("PROJECTS"))
        page.addSpacing(16)

        self.cards = {}
        for project in projects:
            card = ProjectCard(project)
            card.clicked.connect(self.open_project)
            self.cards[project.name] = card
            page.addWidget(card)
            page.addSpacing(10)

        page.addSpacing(14)
        page.addLayout(self._progress_row())

    def _section_heading(self, text: str) -> QHBoxLayout:
        """A small caps label trailed by a hairline across the rest of the width."""
        row = QHBoxLayout()
        row.setSpacing(14)

        label = QLabel(text)
        label.setObjectName("sectionLabel")
        row.addWidget(label)

        rule = QFrame()
        rule.setObjectName("hairline")
        rule.setFixedHeight(1)
        rule.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(rule, 1)
        return row

    def _progress_row(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(10)

        self.status = QLabel("Select a project to open it.")
        self.status.setObjectName("status")
        column.addWidget(self.status)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, STAGE_COUNT)
        self.bar.setValue(0)
        # Keep the bar's space reserved so the cards do not jump when it appears.
        policy = self.bar.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.bar.setSizePolicy(policy)
        self.bar.hide()
        column.addWidget(self.bar)
        return column

    # -- opening a project ---------------------------------------------

    def open_project(self, project: Project):
        if self.viewer is not None:
            return  # already opening one

        self.cards[project.name].set_busy(True)
        self.status.setText(f"Opening {project.name}...")
        self.bar.setRange(0, STAGE_COUNT)
        self.bar.setValue(0)
        self.bar.show()

        # Building the viewer blocks this thread for a moment. Let the busy
        # state paint first.
        QTimer.singleShot(0, lambda: self._start_load(project))

    def _start_load(self, project: Project):
        viewer = wd.MainWindow(project.data_dir, defer_load=True)
        self.viewer = viewer

        loader = viewer.loader
        loader.progress.connect(self.status.setText)
        loader.stage.connect(self._on_stage)
        loader.failed.connect(self._on_failed)
        # Connected after the viewer's own handler, so by the time this runs the
        # scene is already built and the window is worth showing.
        loader.loaded.connect(self._on_loaded)
        loader.start()

    def _on_stage(self, started: int, total: int):
        self.bar.setRange(0, total)
        self.bar.setValue(started)

    def _on_loaded(self, _scene):
        viewer = self.viewer
        if viewer is None:
            return

        self.bar.setValue(self.bar.maximum())
        self.status.setText("Ready")

        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
        viewer.start()
        self.close()  # after the viewer is up, so the application keeps a window

    def _on_failed(self, _message):
        # The viewer has already reported the failure in its own dialog. Put the
        # page back the way it was so the project can be tried again.
        viewer, self.viewer = self.viewer, None
        if viewer is not None:
            viewer.close()
            viewer.deleteLater()

        for card in self.cards.values():
            card.set_busy(False)
        self.bar.hide()
        self.status.setText("Could not open the project. Select it to try again.")

    def closeEvent(self, event):
        viewer = self.viewer
        if viewer is not None and not viewer.isVisible():
            # Closed mid-load: let the viewer shut its loader thread down.
            self.viewer = None
            viewer.close()
        super().closeEvent(event)
