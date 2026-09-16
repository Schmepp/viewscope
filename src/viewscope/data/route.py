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

    @property
    def coverage(self) -> float:
        """The observed fraction, in [0, 1]. Zero when there is nothing to see."""
        return self.observed / self.targets if self.targets else 0.0


class RoutePlan:
    """Which cameras are in the route, and the file it is saved to."""

    def __init__(self):
        self._selected: set[int] = set()
        self.planning = False

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

    def status(self, plan, observed: int = 0, targets: int = 0) -> RouteStatus:
        selected = self.selected
        ids = () if plan is None else plan.ids

        return RouteStatus(
            planning=self.planning,
            selected=selected,
            labels=tuple(ids[i] if i < len(ids) else f"#{i + 1}" for i in selected),
            camera_count=len(ids),
            observed=int(observed),
            targets=int(targets),
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
        """Write the route out. Returns the path actually written."""
        path = Path(path)
        path.write_text(json.dumps(self.document(plan, observed, targets), indent=2))

        return path


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
