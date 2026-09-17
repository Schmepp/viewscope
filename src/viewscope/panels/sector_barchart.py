"""The Bar-chart for the sector. Every bar represents a sector(so either 4 or 8 bars).
The Y-axis represents the best weight. There's also a line drawn across screen.
I looked at the official PyQt6 docs for an example and took inspiration from it:
https://doc.qt.io/qtforpython-6/examples/example_charts_barchart.html"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from viewscope.scene.target_report import TargetReport


class SectorBarChart(QWidget):
    """Bar Chart for best weight per sector, and a line for the average."""

    def __init__(self):
        super().__init__()

        # self.set_0 = QBarSet("Jane")
        # self.set_1 = QBarSet("John")
        # self.set_2 = QBarSet("Axel")
        # self.set_3 = QBarSet("Mary")
        # self.set_4 = QBarSet("Samantha")

        # self.set_0.append([1, 2, 3, 4, 5, 6])
        # self.set_1.append([5, 0, 0, 4, 0, 7])
        # self.set_2.append([3, 5, 8, 13, 8, 5])
        # self.set_3.append([5, 6, 7, 3, 4, 5])
        # self.set_4.append([9, 7, 5, 3, 1, 2])

        # self.series = QBarSeries()
        # self.series.append(self.set_0)
        # self.series.append(self.set_1)
        # self.series.append(self.set_2)
        # self.series.append(self.set_3)
        # self.series.append(self.set_4)

        self.chart = QChart()
        self.chart.setTitle("Best Weight Per Sector")
        # self.chart.setAnimationOptions(QChart.SeriesAnimations)
        self.chart.legend().setVisible(True)

        self.view = QChartView(self.chart)  #
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        ## Example from the docs
        # self.categories = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        # self.axis_x = QBarCategoryAxis()
        # self.axis_x.append(self.categories)
        # self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        # self.series.attachAxis(self.axis_x)

        # self.axis_y = QValueAxis()
        # self.axis_y.setRange(0, 15)
        # self.chart.addAxis(self.axis_y, Qt.AlignLeft)
        # self.series.attachAxis(self.axis_y)

        # self.chart.legend().setVisible(True)
        # self.chart.legend().setAlignment(Qt.AlignBottom)

        # self._chart_view = QChartView(self.chart)
        # self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)

    def update_chart(self, report: TargetReport):
        """Update the bar chart with the latest report.
        This should be called whenever a new target is picked."""
        self.chart.removeAllSeries()  # clear chart
