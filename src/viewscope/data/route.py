"""
The subset of viewpoints the user has chosen to fly.

Route planning starts from the whole plan and takes cameras away: a survey
usually flies fewer viewpoints than were generated for it, and the question
being answered is how much of the model the ones left still see. The chosen
ids are what gets written out, in the same shape as the plan.json they came
from, so a saved route loads straight back as a plan.

No Qt and no VTK here, so the whole thing can be exercised without a window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from viewscope_core.loaders import PLAN_FRAME

ROUTE_VERSION = 1

#: The sectors the ground plane is cut into about the model, each an eighth
#: of the way round it: sector 1 opens at +x and they go anticlockwise, the
#: way a Cartesian plane numbers its quadrants. Eight rather than four because
#: a route can stand in all four quadrants and still leave two whole faces of
#: a building unseen, which eighths show and quarters hide. It is also the
#: decomposition the bundle scores its targets by.
SECTORS = 8

#: Where the sector lines meet when nobody says otherwise. Callers holding a
#: scene pass its centre instead, because a bundle need not sit at 0, 0.
WORLD_ORIGIN = (0.0, 0.0)

#: Past this a pitch has no defined roll, which is where camera_pose gives up.
PITCH_LIMIT_DEG = 89.9


@dataclass(frozen=True)
class RouteEntry:
    """One viewpoint read out of a route file."""

    id: str
    position: np.ndarray
    yaw_deg: float
    pitch_deg: float


@dataclass(frozen=True)
class RouteStatus:
    """Everything the panel shows, as plain numbers."""

    planning: bool
    #: Plan rows in the route, ascending.
    selected: tuple[int, ...]
    #: The plan id of each selected row, in the same order.
    labels: tuple[str, ...]
    camera_count: int
    #: Targets at least one selected camera can see, of the targets there are.
    observed: int = 0
    targets: int = 0
    #: How many cameras of the route stand in each sector of the ground
    #: plane, sector 1 first. Empty when there was no plan to measure.
    sectors: tuple[int, ...] = ()

    @property
    def coverage(self) -> float:
        """The observed fraction, in [0, 1]. Zero when there is nothing to see."""
        return self.observed / self.targets if self.targets else 0.0

    @property
    def sector_shares(self) -> tuple[float, ...]:
        """The fraction of the route standing in each sector, summing to one.

        All zeros while the route is empty, which is a chart with nothing to
        draw rather than eight equal bars.
        """
        total = sum(self.sectors)
        if not total:
            return tuple(0.0 for _ in self.sectors)

        return tuple(count / total for count in self.sectors)


class RoutePlan:
    """Which cameras are in the route, and the file it is saved to."""

    def __init__(self):
        self._selected: set[int] = set()
        self.planning = False

        # The file this route belongs to: the one it was loaded from, or the
        # one it was last written to. None until it has been either, which is
        # what a route planned from scratch is.
        self.path: Path | None = None

    def came_from(self, path):
        """Remember the file this route was read out of."""
        self.path = None if path is None else Path(path)

    def forget_file(self):
        """Let go of that file, for when another bundle is opened."""
        self.path = None

    # -- selection -----------------------------------------------------

    def start(self, camera_count: int):
        """Begin planning with every camera in the route."""
        self.planning = True
        self.select_all(camera_count)

    def stop(self):
        """Leave planning. The selection is kept, in case it is picked up again."""
        self.planning = False

    def select_all(self, camera_count: int):
        self._selected = set(range(int(camera_count)))

    def clear(self):
        self._selected.clear()

    def select(self, indices):
        """Replace the route with exactly these plan rows."""
        self._selected = {int(index) for index in indices}

    def resume(self):
        """Carry on planning with whatever is already in the route."""
        self.planning = True

    def toggle(self, index: int) -> bool:
        """Flip one camera in or out of the route. Returns whether it is now in."""
        index = int(index)
        if index in self._selected:
            self._selected.discard(index)
            return False

        self._selected.add(index)

        return True

    def forget_beyond(self, camera_count: int):
        """Drop rows a shrinking plan no longer has."""
        self._selected = {i for i in self._selected if i < int(camera_count)}

    @property
    def selected(self) -> tuple[int, ...]:
        """The chosen plan rows, ascending."""
        return tuple(sorted(self._selected))

    def __contains__(self, index) -> bool:
        return int(index) in self._selected

    def __len__(self) -> int:
        return len(self._selected)

    # -- reporting -----------------------------------------------------

    def status(
        self,
        plan,
        observed: int = 0,
        targets: int = 0,
        origin=WORLD_ORIGIN,
    ) -> RouteStatus:
        """`origin` is where the sector lines meet: the model's centre."""
        selected = self.selected
        ids = () if plan is None else plan.ids
        rows = [i for i in selected if i < len(ids)]

        return RouteStatus(
            planning=self.planning,
            selected=selected,
            labels=tuple(ids[i] if i < len(ids) else f"#{i + 1}" for i in selected),
            camera_count=len(ids),
            observed=int(observed),
            targets=int(targets),
            sectors=() if plan is None else count_sectors(plan.positions[rows], origin),
        )

    def document(self, plan, observed: int = 0, targets: int = 0) -> dict:
        """The route as the JSON it is saved as, which is also a valid plan."""
        selected = self.selected
        status = self.status(plan, observed, targets)

        return {
            "version": ROUTE_VERSION,
            "frame": PLAN_FRAME,
            "units": "metres",
            "camera": dict(plan.camera),
            "coverage": {
                "targets": status.targets,
                "observed": status.observed,
                "fraction": round(status.coverage, 6),
                "cameras": len(selected),
                "cameras_available": status.camera_count,
            },
            "viewpoints": [
                {
                    "id": plan.ids[i],
                    "index": int(i),
                    "position": [float(v) for v in np.asarray(plan.positions[i])],
                    "yaw_deg": float(plan.yaws_deg[i]),
                    "pitch_deg": float(plan.pitches_deg[i]),
                }
                for i in selected
            ],
        }

    def save(self, path, plan, observed: int = 0, targets: int = 0) -> Path:
        """Write the route out. Returns the path actually written.

        The route belongs to that file afterwards, so saving it again offers
        the same one rather than starting the naming over.
        """
        path = Path(path)
        path.write_text(json.dumps(self.document(plan, observed, targets), indent=2))
        self.path = path

        return path


def count_sectors(positions, origin=WORLD_ORIGIN, sectors: int = SECTORS) -> tuple[int, ...]:
    """How many of these cameras stand in each sector of the ground plane.

    The plan frame is z-up, so the plane the model sits on is x against y and
    a camera's sector is the direction it stands in from the model, cut into
    `sectors` equal wedges: sector 1 opens at +x and they run anticlockwise,
    the way a Cartesian plane numbers its quadrants. Height plays no part - a
    camera above the model is still east of it.

    The direction is taken about `origin`, which is where the model sits
    rather than where the world begins. A bundle cut out of a larger survey
    carries that survey's coordinates, so measuring from 0, 0 would put every
    camera of it in one sector and say nothing about how the route surrounds
    the model. Pass `SceneData.centre`; the default is for callers with no
    scene.

    A camera standing exactly on a boundary belongs to the sector that
    boundary opens, and one standing on the centre itself to sector 1.
    """
    counts = [0] * int(sectors)

    points = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    if len(points):
        ground = points[:, :2] - np.asarray(origin, dtype=np.float64).reshape(-1)[:2]
        # Anticlockwise from +x, which is what numbering the sectors means.
        bearing = np.mod(np.arctan2(ground[:, 1], ground[:, 0]), 2.0 * np.pi)
        found = np.minimum(
            np.floor(bearing * sectors / (2.0 * np.pi)).astype(np.int64),
            int(sectors) - 1,
        )
        for sector in found:
            counts[int(sector)] += 1

    return tuple(counts)


def load_route(path) -> tuple[RouteEntry, ...]:
    """Read the viewpoints named by a route file.

    Takes anything shaped like a plan: a route this application saved, or the
    plan.json a bundle ships. Raises ValueError, with something worth showing
    a person, for a file that is not one.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text())
    except OSError as error:
        raise ValueError(f"{path.name} could not be read: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is not valid json: {error}") from error

    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} is not a route document")

    viewpoints = raw.get("viewpoints")
    if not isinstance(viewpoints, list) or not viewpoints:
        raise ValueError(f"{path.name} names no viewpoints")

    entries = tuple(_entry(index, viewpoint) for index, viewpoint in enumerate(viewpoints))
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError(f"{path.name} names the same viewpoint more than once")

    return entries


def _entry(index: int, viewpoint) -> RouteEntry:
    """One viewpoint of a route file, checked hard enough to fly."""
    if not isinstance(viewpoint, dict):
        raise ValueError(f"viewpoint {index} is not an object")

    name = viewpoint.get("id")
    if not isinstance(name, str) or not name:
        raise ValueError(f"viewpoint {index} has no id")

    position = viewpoint.get("position")
    if not (isinstance(position, list) and len(position) == 3):
        raise ValueError(f"{name} position must be a list of three numbers")

    try:
        position = np.asarray(position, dtype=np.float64)
        yaw = float(viewpoint.get("yaw_deg", np.nan))
        pitch = float(viewpoint.get("pitch_deg", np.nan))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} has a pose that is not numeric: {error}") from error

    if not (np.all(np.isfinite(position)) and np.isfinite(yaw) and np.isfinite(pitch)):
        raise ValueError(f"{name} has a pose that is not a finite number")

    if abs(pitch) > PITCH_LIMIT_DEG:
        raise ValueError(f"{name} pitch of {pitch} deg is too close to vertical")

    return RouteEntry(id=name, position=position, yaw_deg=yaw, pitch_deg=pitch)
