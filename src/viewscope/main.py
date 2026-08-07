import viewscope_core as vc


def main():
    print("Hello world from ViewScope!")

    # NOTE: The code below was copied from the README that came with the
    # scaffold code. This code isn't actually intended to do anything. We're
    # only calling it here to ensure our dev environment is properly setup and
    # that all the required libraries have been imported correctly.

    plan = vc.load_plan("data/kiri/plan.json")
    v, f, colors, edges = vc.camera_glyph(plan.positions[0],
        plan.yaws_deg[0], plan.pitches_deg[0])

    mesh = vc.load_scene("data/kiri/scene.obj")
    targets, normals = vc.load_targets("data/kiri/targets.ply")
    r = vc.SceneRenderer(mesh, 1368, 912, 53.1301)
    pose = vc.camera_pose([190.0, 105.0, 5.0], 30.0, -20.0)
    row = vc.camera_visibility(r.render_depth(pose), targets, normals,
        [190.0, 105.0, 5.0], pose, plan.camera)
    r.close()
