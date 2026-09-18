"""
The two charts the route panel reads itself through.

`CoverageBar` answers the question route planning is about - how much of the
model the cameras still in the route can see - as one bar filled to the share
of targets they observe between them. `QuadrantPie` answers the other half:
whether those cameras stand all around the model or bunched on one side of it,
as the share of the route in each quadrant of the ground plane it sits on.

Both are fed a `RouteStatus` and nothing else. Each builds its series, its
axes and its slices once and then only rewrites the numbers in them: a chart
that drops them on every update draws the old ones over the new, and the route
changes on every click.

A quadrant keeps its colour whether or not the route puts a camera in it, so
the pie means the same thing from one click to the next. The four are a
validated categorical set - they hold apart under deuteranopia, protanopia and
tritanopia - and each slice is labelled as well as coloured, so the chart never
rests on colour alone.

Built with QtCharts, the way `sector_barchart.py` builds the target's chart.
"""

from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalStackedBarSeries,
    QPieSeries,
    QPieSlice,
    QValueAxis,
)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from viewscope.data.route import QUADRANTS, RouteStatus

#: One colour per quadrant, in quadrant order, and never reassigned: the
#: colour says which quadrant, not how big the slice is.
QUADRANT_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7")

#: The two ends of the coverage bar: what the route sees, and what is left.
OBSERVED_COLOUR = "#e34948"
UNOBSERVED_COLOUR = "#ffffff"

#: White on a white chart is nothing at all, so the unobserved end is given
#: an edge to be read by. Without it the bar would look as though it simply
#: stopped where the coverage ended, with no whole to be a part of.
UNOBSERVED_EDGE = "#b8b6b0"

#: The pie stands to the left of its legend, which is the only way four
#: labelled quadrants fit across a dock this narrow.
PIE_WIDTH = 0.62


class _ChartWidget(QWidget):
    """A chart filling the widget, with room for a dock this narrow."""

    def __init__(self, height: int):
        super().__init__()

        self.chart = QChart()
        self.chart.setMargins(QMargins(2, 2, 2, 2))

        self.view = QChartView(self.chart)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setMinimumHeight(height)


class CoverageBar(_ChartWidget):
    """One bar: the targets the route sees, against the targets there are."""

    def __init__(self):
        super().__init__(130)

        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

        self._observed = QBarSet("Observed")
        self._observed.setColor(QColor(OBSERVED_COLOUR))
        self._observed.setPen(QPen(Qt.PenStyle.NoPen))
        self._observed.append([0.0])

        self._unobserved = QBarSet("Not observed")
        self._unobserved.setColor(QColor(UNOBSERVED_COLOUR))
        self._unobserved.setPen(QPen(QColor(UNOBSERVED_EDGE), 1))
        self._unobserved.append([0.0])

        series = QHorizontalStackedBarSeries()
        series.append(self._observed)
        series.append(self._unobserved)
        self.chart.addSeries(series)

        # One nameless row: the bar is the whole chart, so a label down the
        # side would only repeat the title.
        self._axis_row = QBarCategoryAxis()
        self._axis_row.append([""])
        self.chart.addAxis(self._axis_row, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(self._axis_row)

        self._axis_targets = QValueAxis()
        self._axis_targets.setLabelFormat("%d")
        self.chart.addAxis(self._axis_targets, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(self._axis_targets)

        self.update_chart(None)

    def update_chart(self, status: RouteStatus | None):
        """Redraw for this route, or empty the bar when there is no scene."""
        targets = 0 if status is None else status.targets
        observed = 0 if status is None else min(status.observed, targets)

        self.chart.setTitle(
            "No targets to observe"
            if status is None or not targets
            else f"Observed {status.observed:,} of {targets:,} targets"
        )

        self._observed.replace(0, float(observed))
        self._unobserved.replace(0, float(targets - observed))
        # A scene with no targets would give a zero width axis, which draws as
        # a row of zeroes, so the bar keeps a nominal length with no scale on it.
        self._axis_targets.setRange(0.0, float(targets) if targets else 1.0)
        self._axis_targets.setLabelsVisible(bool(targets))


class QuadrantPie(_ChartWidget):
    """A slice per quadrant of the ground plane, holding the route's share."""

    def __init__(self):
        super().__init__(230)

        # Down the side rather than along the bottom: four entries carrying a
        # count and a share would be cut to "Q1 3 (..." on one row.
        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)

        self._series = QPieSeries()
        # Qt draws the first slice from twelve o'clock clockwise, which would
        # run the quadrants backwards; starting at three and going the other
        # way lays them out the way the plane numbers them.
        self._series.setPieStartAngle(90.0)
        self._series.setPieEndAngle(-270.0)
        self._series.setPieSize(0.88)
        self._series.setHorizontalPosition(PIE_WIDTH / 2.0)
        self._series.setVerticalPosition(0.5)

        self._slices = []
        for quadrant in range(QUADRANTS):
            piece = QPieSlice(f"Q{quadrant + 1}", 0.0)
            piece.setColor(QColor(QUADRANT_COLOURS[quadrant]))
            # The surface showing between the slices is what keeps two of them
            # apart for a reader who cannot tell the two colours apart.
            piece.setBorderColor(QColor(Qt.GlobalColor.white))
            piece.setBorderWidth(2)
            # The legend carries the figures, so nothing is written over the
            # slices themselves - a thin one has no room for it.
            piece.setLabelVisible(False)
            self._series.append(piece)
            self._slices.append(piece)

        self.chart.addSeries(self._series)

        self.update_chart(None)

    def update_chart(self, status: RouteStatus | None):
        """Redraw for this route, or empty the pie when there is no scene."""
        counts = () if status is None else status.quadrants
        shares = () if status is None else status.quadrant_shares
        cameras = sum(counts)

        self.chart.setTitle(
            "Cameras by quadrant: --"
            if not cameras
            else f"Cameras by quadrant: {cameras} in the route"
        )

        # A pie of four zeroes has no whole to be part of, and Qt fills the
        # circle with the last slice rather than drawing nothing, so an empty
        # route takes the pie off the chart altogether and is left to the
        # title, which says the same thing without saying something false.
        self._series.setVisible(bool(cameras))

        for quadrant, piece in enumerate(self._slices):
            count = counts[quadrant] if quadrant < len(counts) else 0
            share = shares[quadrant] if quadrant < len(shares) else 0.0

            # An empty quadrant keeps its place in the legend, so the reader
            # can see it is empty rather than wonder where it went.
            piece.setValue(float(count))
            piece.setLabel(
                f"Q{quadrant + 1}   {count}"
                if not cameras
                else f"Q{quadrant + 1}   {count}  {share:.0%}"
            )
