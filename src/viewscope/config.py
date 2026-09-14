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
# are 0-1 floats and the two are not interchangeable.
IVORY = "#FFFFF0"
INK = "#1F1C15"
MUTED = "#6F6A5B"
HAIRLINE = "#E4DEC6"
CARD = "#FFFDF5"
CARD_HOVER = "#FFFFFF"
CARD_BORDER = "#E6E0C8"
CARD_BORDER_HOVER = "#C9BF98"
ACCENT = "#8A6A3B"
TRACK = "#EDE7D3"


@dataclass(frozen=True)
class Project:
    """One bundle the startup screen can open."""

    name: str
    subtitle: str
    data_dir: Path


PROJECTS = (
    Project(
        name="Kiri Building",
        subtitle="Kiri Vehera mesh, targets and viewpoint plan",
        data_dir=DATA_DIR,
    ),
)
