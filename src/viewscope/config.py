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
