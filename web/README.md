# ViewScope, browser build

A port of the PySide6 + VTK desktop viewer in `src/viewscope/vs_gui.py` to
React, three.js and Cloudflare Pages. Same viewport, same three docks, same
toolbar, menus, shortcuts and status line.

## What it does

Loads the `data/kiri` bundle and lets you inspect the 185 planned viewpoints
against the scan:

- **Viewport** — the vertex-coloured scan mesh, the 60 000 surface targets as
  a score-coloured point cloud, and a camera marker at every planned
  viewpoint. Drag to orbit, right-drag to pan, scroll to zoom.
- **Viewpoints** — one row per planned camera; picking a row flies the
  viewport to that pose using the bundle's own `camera_pose`.
- **Display** — display mode, which scalar field colours the cloud, point
  size, camera-marker visibility, and the colour legend.
- **Metrics** — bundle counts, the current field's min / mean / max, and the
  selected viewpoint's position, yaw and pitch.

### Shortcuts

| Key | Action |
| --- | --- |
| `n`, `→` | next camera |
| `p`, `←` | previous camera |
| `o` | overview |
| `1` `2` `3` `4` | textured / geometry / targets / all |

Docks close from their title bar and come back from the **View** menu; the
arrangement and the rail widths persist in `localStorage`, standing in for the
desktop's `QSettings` + `QMainWindow.saveState()`.

## Running it

```sh
cd web
npm install
npm run export-data   # regenerates public/data from data/kiri
npm run dev
```

`public/data` is gitignored and must be generated before the app will load.

## Deploying to Cloudflare Pages

```sh
npm run deploy        # builds, then wrangler pages deploy dist
```

The first run prompts for a Cloudflare login and creates the `viewscope`
project; after that it publishes to `https://viewscope.pages.dev`. To wire it
to CI instead, point a Pages project at this repo with:

- **Build command** `npm run build`
- **Build output directory** `web/dist`
- **Root directory** `web`

CI has no `data/kiri` to export from, so either commit `web/public/data`
(5.4 MB, well under Pages' 25 MB per-file cap) after dropping the last two
lines of `web/.gitignore`, or make the export a build step. `npm run deploy`
from a working checkout sidesteps this entirely.

`public/_headers` sets the cache policy: the manifest revalidates every load,
the binaries cache for a day, and hashed assets cache forever.

## How the port works

### Data

The desktop parses `scene.obj`, `targets.ply`, `plan.json` and `scores.npz`
through `viewscope_core` on a `QThread`. A browser cannot: `.obj` parsing is
slow in JS and `.npz` is a zip of numpy arrays. So `scripts/export_web_bundle.py`
runs that parse once, through the exact same library, and writes typed-array
blobs that map straight onto WebGL buffers:

| File | Contents |
| --- | --- |
| `mesh_positions.bin` | 74 977 × 3 float32 |
| `mesh_indices.bin` | 150 000 × 3 uint32 |
| `mesh_colors.bin` | 74 977 × 3 uint8 vertex colours |
| `target_positions.bin` | 60 000 × 3 float32 |
| `target_normals.bin` | 60 000 × 3 float32 |
| `field_*.bin` | 60 000 float32 per scalar field |
| `manifest.json` | shapes, bounds, the plan, and per-field min/mean/max |

5.4 MB total, ~2.5 MB over the wire once Cloudflare gzips it.

### Maths

`src/core/pose.ts` and `src/core/glyph.ts` are line-by-line ports of
`viewscope_core.pose` and `viewscope_core.glyph`, including the library's own
assertion that the marker's forward axis agrees with `forward_vector`. Both
were checked against the Python across all 185 viewpoints: pose elements agree
to 4.4e-16, and glyph vertices to 7.6e-6, which is float32 rounding on
coordinates around 200 m. Faces, face colours and edges are identical.

`src/core/lut.ts` reproduces `vtkLookupTable` with `SetHueRange(0.667, 0.0)`,
the blue-to-red ramp the desktop colours the cloud with.

### Actors

`src/viewport/scene.ts` is deliberately imperative and lives outside React,
the same way the desktop keeps its VTK actors outside the Qt widget tree.
React owns the panels; it pushes state into GPU buffers through effects.

| vs_gui.py | Browser |
| --- | --- |
| `vtkRenderer` + `QVTKRenderWindowInteractor` | `SceneView` in a `<div>` |
| `vtkInteractorStyleTrackballCamera` | `OrbitControls`, buttons remapped |
| `mesh_actor` | `THREE.Mesh`, `MeshLambertMaterial` |
| `EdgeVisibilityOn` in geometry mode | a lazily built `WireframeGeometry` |
| `cloud_actor` | `THREE.Points`, `sizeAttenuation: false` |
| `glyph_actors` (185 actors) | two merged buffers, repacked on selection |
| `vtkScalarBarActor` | a CSS gradient in the Display panel |
| default headlight | a `DirectionalLight` parented to the camera |

## Deliberate differences

Three places where a faithful copy would have been worse:

1. **Overview framing.** `vtkRenderer.ResetCamera` inherits the untouched
   `vtkCamera`'s view direction, which for a +Z-up scene means looking
   straight down. That is a gimbal singularity for an orbit controller, so the
   overview is pitched off the pole into a three-quarter view.
2. **Marker colours.** `glyph_actor` guards its colour assignment with
   `len(colors) == len(v)`, but `camera_glyph` returns 16 face colours for 10
   vertices, so the desktop silently drops them and draws white markers. The
   web build applies them per face as the library intends: cyan body, red
   lens.
3. **Line width.** `vtkProperty.SetLineWidth(2.0)` has no WebGL equivalent —
   most drivers clamp `gl_LineWidth` to 1. Marker wireframes are one pixel.

Two things the desktop has that a static page cannot: floating and re-docking
panels between arbitrary edges (docks here close and reopen, and the rails
resize, but they do not tear off), and recomputing visibility for a moved
camera, which needs a live `SceneRenderer` and a GL context in a Python
process.
