"""Constants for the ViewScope viewer.

Nothing here imports Qt or VTK, so any module can pull from it freely.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Relative to the working directory. Pass an explicit path to MainWindow if
# you need to run from somewhere else.
DATA_DIR = Path("data/kiri")

YFOV_DEG = 53.1301

MODE_TEXTURED = "Textured mesh"
MODE_GEOMETRY = "Geometry (.obj)"
MODE_TARGETS = "Target values"
MODE_ALL = "All three"
MODES = [MODE_TEXTURED, MODE_GEOMETRY, MODE_TARGETS, MODE_ALL]

SCALAR_FIELDS = ["score_8", "score_4", "diversity_8", "diversity_4"]

ORG_NAME = "ViewScope"
APP_NAME = "viewer"

BACKGROUND = (0.03, 0.03, 0.05)
GEOMETRY_COLOUR = (0.62, 0.64, 0.70)
EDGE_COLOUR = (0.15, 0.16, 0.20)

# Occlusion highlighting: what the selected camera can and cannot see.
VISIBLE_COLOUR = (0.90, 0.11, 0.14)
OCCLUDED_COLOUR = (0.42, 0.43, 0.47)


# -- target inspection -----------------------------------------------------

# Sector counts the inspector offers. Eight is the default; four is the
# coarser decomposition the bundle also stores a column for.
SECTOR_COUNTS = (8, 4)

COLOUR_BY_WEIGHT = "Weight"
COLOUR_BY_SECTOR = "Sector"
TARGET_COLOUR_MODES = [COLOUR_BY_WEIGHT, COLOUR_BY_SECTOR]

# The picked target itself. Its radius is a fraction of the scene diagonal,
# because bundles differ in scale by an order of magnitude and a marker fixed
# in metres would be a speck on one and a boulder on the next.
TARGET_MARKER_COLOUR = (1.00, 0.84, 0.10)
TARGET_MARKER_FRACTION = 0.0024

# -- route planning --------------------------------------------------------

# A viewpoint in the route, and one the user has taken out of it. Only ever
# worn while planning is on; outside it the glyphs keep their own colours.
ROUTE_SELECTED_COLOUR = (0.16, 0.50, 0.95)
ROUTE_UNSELECTED_COLOUR = (0.34, 0.35, 0.39)

#: What a saved route is called, before the user renames it.
ROUTE_FILENAME = "route.json"


# How far a click may travel, in total, before it counts as a drag of the
# view rather than a pick. Device-independent pixels, summed over the whole
# gesture, so a little hand tremor still reads as a click.
PICK_DRAG_SLOP_PX = 8

# How near the cursor a target has to sit to count as the thing that was
# clicked. Device-independent pixels, measured on screen rather than in
# metres, so the reach is the same however far the view is zoomed out.
PICK_TARGET_RADIUS_PX = 14


@dataclass(frozen=True)
class OverlayOptions:
    """How the picked target is drawn. Plain display state, no VTK in sight."""

    rays: bool = True
    colour_by: str = COLOUR_BY_WEIGHT

    def marker_radius(self, diagonal: float) -> float:
        """The radius of the marker on the picked target, in metres."""
        return float(diagonal) * TARGET_MARKER_FRACTION


# -- startup screen --------------------------------------------------------

# Hex strings, because these are Qt stylesheet values. The VTK colours above
# are 0-1 floats and the two are not interchangeable. Pitched dark, a shade
# above BACKGROUND, so the page and the viewport read as one application.
PAGE = "#121116"
INK = "#F2EFE9"
MUTED = "#918C99"
HAIRLINE = "#2A2831"
CARD = "#1B1A21"
CARD_HOVER = "#232229"
CARD_BORDER = "#2A2831"
CARD_BORDER_HOVER = "#4A4553"
ACCENT = "#8FC5E8"
TRACK = "#26242C"


@dataclass(frozen=True)
class Project:
    """One bundle the startup screen can open."""

    name: str
    subtitle: str
    data_dir: Path
    # The plan size a bundle we ship is known to hold, checked while loading.
    # Projects the user adds bring their own plan, so they leave this None.
    expected_viewpoints: int | None = None

    def as_dict(self) -> dict:
        """The form the startup screen saves an added project in."""
        return {"name": self.name, "subtitle": self.subtitle, "data_dir": str(self.data_dir)}

    @classmethod
    def from_dict(cls, raw: dict) -> Project:
        return cls(
            name=str(raw["name"]),
            subtitle=str(raw.get("subtitle", raw["data_dir"])),
            data_dir=Path(raw["data_dir"]),
        )


PROJECTS = (
    Project(
        name="Kiri Building",
        subtitle="Kiri Vehera mesh, targets and viewpoint plan",
        data_dir=DATA_DIR,
        expected_viewpoints=185,
    ),
    Project(
        name="SeaHawk",
        subtitle="SH-60 airframe, targets and viewpoint plan",
        data_dir=Path("data/SeaHawk"),
        expected_viewpoints=120,
    ),
)
