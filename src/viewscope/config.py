"""Constants for the ViewScope viewer.

Nothing here imports Qt or VTK, so any module can pull from it freely.
"""

from __future__ import annotations

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
