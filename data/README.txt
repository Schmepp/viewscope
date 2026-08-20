ViewScope Resources

Everything here is provided and is not marked. Read GLOSSARY.docx first,
then the brief. scaffold/ is the viewscope_core library: every formula,
constant and geometric computation in this project, behind one API. You
import it and never modify it. data/kiri/ is the dataset.

One world frame everywhere: right handed, +Z up, metres, degrees, nothing
recentred or rescaled. One fixed camera for every viewpoint: 1368 x 912
pixels, vertical field of view 53.1301 degrees.


DATA FORMATS

scene.obj
  Vertex coloured triangle mesh of the scan. The occluder of the visibility
  test and the surface the library renders. Every precomputed number was
  calculated against this exact geometry.

targets.ply
  The 60000 surface targets with outward unit normals. Binary little endian
  PLY: element vertex 60000, properties float x y z nx ny nz, 24 bytes per
  vertex.

plan.json
  The 185 planned viewpoints: id, position, yaw_deg, pitch_deg, rounded to
  4 decimals, plus the camera block (width, height, yfov_deg).

scores.npz
  Precomputed scoring over 1847787 (target, camera) pairs, CSR ordered by
  target then camera: offsets (length 60001), per pair camera_index, weight,
  f_rho, f_theta, sector_8, sector_4, best_8, best_4, and per target
  diversity_8, diversity_4, score_8, score_4. Load with load_scores.

visibility.npz
  visible: bool of shape (185, 60000), rows in plan order, columns in
  targets.ply me, one bit per 0.2 m voxel. Keys: bitsorder. meta: json string.

flyable.npz
  The collision free flight volu
  (numpy packbits), shape, origin, voxel, meta. Voxel [i, j, k] covers the
  cube with minimum corner origin + voxel * (i, j, k). Decode:

    z = np.load("data/kiri/flyable.npz")
    shape = tuple(z["shape"])
    flyable = np.unpackbits(z["bits"], count=int(np.prod(shape))).reshape(shape).astype(bool)

manifest.json
  Byte size and sha256 of every shipped file.


THE LIBRARY

Install: cd scaffold, then pip install -e .
Python 3.11 or newer. Depends on numpy, trimesh, rtree, pyrender, Pillow.
On headless Linux set PYOPENGL_PLATFORM=egl before rendering.

  constants    all model constants. You never type one into your interface
  loaders      load_scene, load_targets, load_plan, load_scores. Fail closed
  pose         camera_pose, forward_vector, look_at_angles, intrinsics,
               project, frustum_corners
  render       SceneRenderer: render_color for photographs, render_depth
               for the visibility test, close to release the GL context
  visibility   camera_visibility for one camera, compute_visibility for a
               whole plan
  scoring      weight_factors, observer_geometry, sector_indices,
               best_per_sector, angular_diversity, target_score
  placement    check_placement, refuses unsafe positions with a reason
  glyph        camera_glyph, the standard viewpoint marker: vertices,
               triangle faces, face colours and wireframe edges, already
               rotated and placed

Draw the plan:

    import viewscope_core as vc
    plan = vc.load_plan("data/kiri/plan.json")
    v, f, colors, edges = vc.camera_glyph(plan.positions[0],
        plan.yaws_deg[0], plan.pitches_deg[0])

Visibility of a camera against the 60000 targets:

    mesh = vc.load_scene("data/kiri/scene.obj")
    targets, normals = vc.load_targets("data/kiri/targets.ply")
    r = vc.SceneRenderer(mesh, 1368, 912, 53.1301)
    pose = vc.camera_pose([190.0, 105.0, 5.0], 30.0, -20.0)
    row = vc.camera_visibility(r.render_depth(pose), targets, normals,
        [190.0, 105.0, 5.0], pose, plan.camera)
    r.close()

Shipped viewpoints are looked up in scores.npz or visibility.npz. Cameras
the user adds or moves are recomputed through the library. The shipped files
were produced by these exact functions, so a recomputation reproduces them
exactly. One live SceneRenderer per process.
