"""Unit tests for src/viewscope/route_report.py.

What the report says is built as text by `report_html`, away from any window,
so what it says is what is checked here: every viewpoint in it, in flying
order, by name and by co-ordinate, and every figure the panel would have
shown. Drawing it onto a page is Qt's, and is not re-tested.
"""

from typing import Any

import numpy as np
import pytest

from viewscope.data.flight_metrics import Drone, estimate_flight, sharpest_turn
from viewscope.data.flight_path import FlightPath
from viewscope.data.route import RouteStatus
from viewscope.route_report import CHART_URLS, report_html

IDS = ("vp000", "vp001", "vp002", "vp003")
POSITIONS = np.array(
    [
        [0.0, 0.0, 10.0],
        [30.0, 0.0, 10.0],
        [30.0, 40.0, 12.5],
        [0.0, 40.0, 10.0],
    ]
)


@pytest.fixture
def path():
    """A route flown 0 -> 2 -> 1, which turns a right angle in the middle."""
    points = np.array([[0.0, 0, 0], [40, 0, 0], [40, 30, 0]])

    return FlightPath(
        order=(0, 2, 1),
        points=points,
        length=70.0,
        detours=1,
        climbs=0,
        crossings=0,
        checked=True,
    )


@pytest.fixture
def status():
    return RouteStatus(
        planning=True,
        selected=(0, 1, 2),
        labels=("vp000", "vp001", "vp002"),
        camera_count=4,
        observed=4_200,
        targets=9_000,
        sectors=(2, 0, 1, 0, 0, 0, 0, 0),
    )


@pytest.fixture
def html(status, path):
    def build(**overrides):
        drone = overrides.pop("drone", Drone())
        settings: dict[str, Any] = {
            "name": "north_face",
            "bundle": "kiri",
            "status": status,
            "path": path,
            "ids": IDS,
            "positions": POSITIONS,
            "turn": sharpest_turn(path.points),
            "flight": estimate_flight(path.points, stops=len(path.order), drone=drone),
            "drone": drone,
        }
        settings.update(overrides)

        return report_html(**settings)

    return build


# -----------------------------------------------------------------------------
# What the route is
# -----------------------------------------------------------------------------


def test_the_route_is_named(html):
    assert "north_face" in html()
    assert "kiri" in html()


def test_a_name_with_markup_in_it_is_written_as_text(html):
    """A file can be called anything; a document that took it as a tag could not."""
    document = html(name="<b>north</b> & south")

    assert "&lt;b&gt;north&lt;/b&gt; &amp; south" in document
    assert "<b>north</b>" not in document


def test_the_coverage_the_panel_shows_is_in_it(html):
    document = html()

    assert "4,200 of 9,000" in document
    assert "46.7%" in document


# -----------------------------------------------------------------------------
# The path, twice over
# -----------------------------------------------------------------------------


def test_the_path_is_given_as_viewpoints_in_flying_order(html):
    document = html()

    assert "vp000 &rarr; vp002 &rarr; vp001" in document


def test_every_viewpoint_flown_is_given_as_a_co_ordinate(html):
    document = html()

    for row in (0, 2, 1):
        x, y, z = POSITIONS[row]
        assert f"{x:,.2f}" in document
        assert f"{y:,.2f}" in document
        assert f"{z:,.2f}" in document


def test_a_viewpoint_left_out_of_the_route_is_left_out_of_the_report(html):
    """vp003 is in the plan and not in the path, so it is not a stop."""
    assert "vp003" not in html()


def test_the_length_is_the_path_is_own(html, path):
    assert f"{path.length:,.0f} m" in html()


def test_the_sharpest_turn_is_reported_with_its_place(html):
    document = html()

    assert "90&deg; at stop 1" in document
    assert "straight on is 180" in document


def test_a_path_with_no_corner_says_so(html, path, status):
    straight = FlightPath(
        order=(0, 1),
        points=np.array([[0.0, 0, 0], [10, 0, 0]]),
        length=10.0,
        detours=0,
        climbs=0,
        crossings=0,
        checked=True,
    )

    assert "no corner to turn at" in html(path=straight, turn=sharpest_turn(straight.points))


def test_an_empty_route_says_there_is_nothing_to_fly(html):
    empty = FlightPath(
        order=(),
        points=np.zeros((0, 3)),
        length=0.0,
        detours=0,
        climbs=0,
        crossings=0,
        checked=False,
    )

    assert "no path to fly" in html(path=empty, turn=None)


# -----------------------------------------------------------------------------
# What it would cost to fly
# -----------------------------------------------------------------------------


def test_the_energy_is_given_in_watt_hours_and_in_joules(html, path):
    flight = estimate_flight(path.points, stops=3)
    document = html()

    assert f"{flight.energy_wh:,.1f} Wh" in document
    assert f"{flight.energy_kj:,.0f} kJ" in document


def test_the_share_of_a_battery_is_given(html):
    assert "of a 74 Wh pack" in html()


def test_a_flight_needing_more_than_a_pack_says_so(html):
    assert "more than one battery" in html(drone=Drone(battery_wh=0.001))


def test_every_assumption_behind_the_figure_is_printed(html):
    """An estimate whose assumptions are not stated cannot be argued with."""
    document = html(drone=Drone(mass_kg=2.4, cruise_speed_ms=7.0, dwell_s=3.0))

    assert "2.4 kg" in document
    assert "7 m/s" in document
    assert "3 s held at each" in document
    assert "momentum theory" in document


# -----------------------------------------------------------------------------
# The charts
# -----------------------------------------------------------------------------


def test_both_charts_are_in_the_document(html):
    document = html()

    assert CHART_URLS["coverage"] in document
    assert CHART_URLS["sectors"] in document


def test_the_sectors_are_said_in_words_as_well_as_drawn(html):
    """A chart is no use to a reader who cannot see it, and none to a grep."""
    document = html()

    assert "2 of the 8 sectors" in document
    assert "S1 2 (67%)" in document
    assert "S3 1 (33%)" in document


def test_a_document_without_charts_leaves_the_images_out(html):
    document = html(charts=False)

    assert CHART_URLS["coverage"] not in document
    assert "The path, by viewpoint" in document
