"""Convert the kiri bundle into flat binaries the browser can fetch directly.

The desktop app (src/viewscope/vs_gui.py) parses scene.obj, targets.ply,
plan.json and scores.npz through viewscope_core at start-up. A browser cannot
do that: .obj parsing is slow in JS and .npz is a zip of numpy arrays. So we
do the parsing once, here, through the exact same library, and ship typed
array blobs that map straight onto WebGL buffers.

Run from the repo root:

    uv run python scripts/export_web_bundle.py

Writes into web/public/data/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import viewscope_core as vc  # noqa: E402

DATA = ROOT / "data/kiri"
OUT = ROOT / "web/public/data"

# vs_gui.py offers exactly these four in the "Colour by" combo box.
SCALAR_FIELDS = ["score_8", "score_4", "diversity_8", "diversity_4"]


def write(name: str, array: np.ndarray) -> dict:
    """Dump a C-contiguous array and describe it for the manifest."""
    array = np.ascontiguousarray(array)
    path = OUT / name
    path.write_bytes(array.tobytes())
    return {
        "file": name,
        "dtype": array.dtype.name,
        "count": int(array.size),
        "components": int(array.shape[1]) if array.ndim > 1 else 1,
        "bytes": int(array.nbytes),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"version": 1, "frame": "z-up-right-handed", "units": "metres"}

    # ---- mesh ------------------------------------------------------------
    print("loading scene.obj ...")
    mesh = vc.load_scene(str(DATA / "scene.obj"))
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)

    # The bundle's scene.obj is vertex coloured, so visual.kind == "vertex"
    # and texture_from_mesh() returns None on the desktop too. "Textured mesh"
    # mode therefore means "shaded with vertex colours" in both apps.
    kind = getattr(mesh.visual, "kind", None)
    colors = None
    if kind == "vertex":
        colors = np.ascontiguousarray(mesh.visual.vertex_colors[:, :3], dtype=np.uint8)

    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    manifest["mesh"] = {
        "positions": write("mesh_positions.bin", vertices),
        "indices": write("mesh_indices.bin", faces),
        "colors": write("mesh_colors.bin", colors) if colors is not None else None,
        "vertexCount": int(len(vertices)),
        "triangleCount": int(len(faces)),
        "bounds": bounds.tolist(),
        "diagonal": float(np.linalg.norm(bounds[1] - bounds[0])),
        "visualKind": kind,
    }

    # ---- targets ---------------------------------------------------------
    print("loading targets.ply ...")
    targets, normals = vc.load_targets(str(DATA / "targets.ply"))
    manifest["targets"] = {
        "positions": write(
            "target_positions.bin", np.asarray(targets, dtype=np.float32)
        ),
        "normals": write("target_normals.bin", np.asarray(normals, dtype=np.float32)),
        "count": int(len(targets)),
    }

    # ---- plan ------------------------------------------------------------
    print("loading plan.json ...")
    plan = vc.load_plan(str(DATA / "plan.json"))
    manifest["plan"] = {
        "camera": dict(plan.camera),
        "count": int(len(plan.positions)),
        "viewpoints": [
            {
                "id": f"vp{i:03d}",
                "position": [float(c) for c in plan.positions[i]],
                "yaw_deg": float(plan.yaws_deg[i]),
                "pitch_deg": float(plan.pitches_deg[i]),
            }
            for i in range(len(plan.positions))
        ],
    }

    # ---- scores ----------------------------------------------------------
    print("loading scores.npz ...")
    fields: dict = {}
    try:
        scores = vc.load_scores(
            str(DATA / "scores.npz"), len(targets), len(plan.positions)
        )
        for field in SCALAR_FIELDS:
            values = np.ascontiguousarray(getattr(scores, field), dtype=np.float32)
            entry = write(f"field_{field}.bin", values)
            # The desktop Metrics panel shows min/mean/max; precompute so the
            # browser does not have to reduce 60k floats on every switch.
            entry["min"] = float(values.min())
            entry["mean"] = float(values.mean())
            entry["max"] = float(values.max())
            fields[field] = entry
        manifest["scores"] = {"fields": fields, "order": SCALAR_FIELDS}
        manifest["scoresError"] = None
    except Exception as exc:  # matches the desktop's fail-soft behaviour
        manifest["scores"] = None
        manifest["scoresError"] = f"{type(exc).__name__}: {exc}"
        print(f"scores unavailable: {exc}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))

    total = sum(p.stat().st_size for p in OUT.iterdir() if p.is_file())
    print(f"\nwrote {len(list(OUT.iterdir()))} files, {total / 1e6:.1f} MB, to {OUT}")


if __name__ == "__main__":
    main()
