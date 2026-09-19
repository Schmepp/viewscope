"""
What a planned flight path costs to fly, and how hard it turns.

`flight_path.py` answers where the drone goes. This answers two things the
report asks about that line afterwards:

    the sharpest turn   the tightest corner in the flown line, as the angle
                        the drone is left with between coming in and going
                        out. Flying straight on is 180 degrees; doubling
                        back on itself is 0. It is the corner a pilot looks
                        for, because it is the one the aircraft has to stop
                        dead in.
    the energy          what the flight would take out of a battery.

The energy is an estimate, not a measurement, and it is worth being plain
about what it rests on. Hover power comes from momentum theory: to hold
itself up an aircraft of weight T must throw air down through the disc its
rotors sweep, and the least power that can do it is

    P_ideal = T^1.5 / sqrt(2 * rho * A)

with A the whole disc area. Real rotors are worse than ideal by their figure
of merit, and the motors and speed controllers behind them lose some of what
the battery gives, so the shaft figure is divided by both. The avionics draw
their own watts whatever the rotors are doing.

The flight itself is taken as it is actually flown on a survey: from rest at
one viewpoint, up to cruising speed, back to rest at the next, and a pause
there to take the photograph. A hop too short to reach cruising speed is
flown as accelerate-then-brake. Forward flight is costed at hover power,
which is a little pessimistic - a rotor moving through air is slightly more
efficient than one holding still in it - and the margin is left in on
purpose, since the alternative is a report that promises a battery will last
longer than it does.

Pure numpy. No Qt, no VTK and no scene, so all of it can be exercised
headless.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from viewscope.config import (
    AIR_DENSITY,
    DRONE_ACCELERATION_MS2,
    DRONE_AVIONICS_W,
    DRONE_BATTERY_WH,
    DRONE_CRUISE_SPEED_MS,
    DRONE_DRIVE_EFFICIENCY,
    DRONE_DWELL_S,
    DRONE_FIGURE_OF_MERIT,
    DRONE_MASS_KG,
    DRONE_ROTOR_RADIUS_M,
    DRONE_ROTORS,
)

#: Standard gravity, m/s^2.
GRAVITY = 9.80665

#: Seconds in an hour, which is all that stands between joules and watt-hours.
SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Turn:
    """The tightest corner in a flown line."""

    #: The angle left between coming in and going out, in degrees. Straight
    #: on is 180; a corner that doubles back is 0.
    angle_deg: float
    #: Which point of the line it is at, and how far along the line that is.
    index: int
    distance_m: float
    #: How many corners there were to choose from.
    corners: int


@dataclass(frozen=True)
class Drone:
    """The aircraft a path is costed against, and what it can be told to do."""

    mass_kg: float = DRONE_MASS_KG
    rotors: int = DRONE_ROTORS
    rotor_radius_m: float = DRONE_ROTOR_RADIUS_M
    air_density: float = AIR_DENSITY
    figure_of_merit: float = DRONE_FIGURE_OF_MERIT
    drive_efficiency: float = DRONE_DRIVE_EFFICIENCY
    avionics_w: float = DRONE_AVIONICS_W
    cruise_speed_ms: float = DRONE_CRUISE_SPEED_MS
    acceleration_ms2: float = DRONE_ACCELERATION_MS2
    dwell_s: float = DRONE_DWELL_S
    battery_wh: float = DRONE_BATTERY_WH

    @property
    def disc_area_m2(self) -> float:
        """The whole area the rotors sweep between them."""
        return self.rotors * math.pi * self.rotor_radius_m**2

    @property
    def hover_power_w(self) -> float:
        """What the battery gives up to hold the aircraft still in the air."""
        thrust = self.mass_kg * GRAVITY
        ideal = thrust**1.5 / math.sqrt(2.0 * self.air_density * self.disc_area_m2)

        return ideal / (self.figure_of_merit * self.drive_efficiency) + self.avionics_w


@dataclass(frozen=True)
class Flight:
    """What flying one path would take."""

    #: How long it is in the air, in seconds, and what that splits into.
    seconds: float
    flying_seconds: float
    dwelling_seconds: float
    #: How much it draws while it is up there, in watts.
    power_w: float
    #: And what that comes to, in watt-hours and in kilojoules.
    energy_wh: float
    #: What share of one battery that is. 1.0 is the whole pack.
    battery_share: float
    #: How many stops were dwelt at, and how far was flown between them.
    stops: int
    distance_m: float

    @property
    def energy_kj(self) -> float:
        return self.energy_wh * SECONDS_PER_HOUR / 1000.0

    @property
    def within_one_battery(self) -> bool:
        return self.battery_share <= 1.0


def sharpest_turn(points) -> Turn | None:
    """The tightest corner in this line, or None when it has no corner at all.

    Measured at every point with a hop either side of it. Points that repeat,
    which a path round a building can leave behind, are dropped first: a hop
    of no length has no direction to turn from.
    """
    line = _distinct(points)
    if len(line) < 3:
        return None

    legs = np.diff(line, axis=0)
    lengths = np.linalg.norm(legs, axis=1)
    directions = legs / lengths[:, None]

    # The angle between where it was going and where it goes next, taken the
    # way round that leaves a straight line at 180 degrees.
    turned = np.einsum("ij,ij->i", directions[:-1], directions[1:])
    angles = np.degrees(np.arccos(np.clip(turned, -1.0, 1.0)))
    interior = 180.0 - angles

    corner = int(np.argmin(interior))
    travelled = float(lengths[: corner + 1].sum())

    return Turn(
        angle_deg=float(interior[corner]),
        index=corner + 1,
        distance_m=travelled,
        corners=int(len(interior)),
    )


def estimate_flight(points, stops: int | None = None, drone: Drone | None = None) -> Flight:
    """What flying this line would take out of a battery.

    `stops` is how many viewpoints are dwelt at; by default every point of
    the line is taken as one, which is right for a line drawn straight
    through its viewpoints and wrong for one that goes round a building, so
    the caller that knows passes the number in.
    """
    drone = drone or Drone()
    line = _distinct(points)

    hops = (
        np.linalg.norm(np.diff(line, axis=0), axis=1)
        if len(line) > 1
        else np.zeros(0, dtype=np.float64)
    )
    flying = float(sum(_hop_seconds(float(hop), drone) for hop in hops))

    stops = len(line) if stops is None else int(stops)
    dwelling = max(stops, 0) * drone.dwell_s

    seconds = flying + dwelling
    power = drone.hover_power_w
    energy_wh = power * seconds / SECONDS_PER_HOUR

    return Flight(
        seconds=seconds,
        flying_seconds=flying,
        dwelling_seconds=dwelling,
        power_w=power,
        energy_wh=energy_wh,
        battery_share=energy_wh / drone.battery_wh if drone.battery_wh > 0 else 0.0,
        stops=max(stops, 0),
        distance_m=float(hops.sum()),
    )


# -- internals -------------------------------------------------------------


def _hop_seconds(distance: float, drone: Drone) -> float:
    """How long one hop takes, flown from rest and stopped at the far end."""
    if distance <= 0.0:
        return 0.0

    speed, accel = drone.cruise_speed_ms, drone.acceleration_ms2
    if speed <= 0.0 or accel <= 0.0:
        return 0.0

    # How far it takes to wind up to cruising speed and back down again. A
    # hop shorter than that never gets there: it is half acceleration and
    # half braking, and the peak is whatever the middle of it reaches.
    ramp = speed**2 / accel
    if distance <= ramp:
        return 2.0 * math.sqrt(distance / accel)

    return distance / speed + speed / accel


def _distinct(points) -> np.ndarray:
    """The line with any point repeating the one before it dropped."""
    line = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(line) < 2:
        return line

    moved = np.linalg.norm(np.diff(line, axis=0), axis=1) > 0.0

    return line[np.concatenate(([True], moved))]
