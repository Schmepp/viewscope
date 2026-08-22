/**
 * Port of viewscope_core.pose.
 *
 * The world frame is right handed with +Z up, metres and degrees, and the
 * camera convention is pyrender / OpenGL: the camera looks down its own -Z
 * with +Y up, so the rotation block's columns are the camera axes in world
 * space. Numbers here must match the Python library exactly, because the
 * shipped scores were computed against it.
 */

export type Vec3 = [number, number, number];
/** Row-major 4x4, indexed `m[row][col]`, same as the numpy arrays. */
export type Mat4 = number[][];

const DEG = Math.PI / 180;

export function forwardVector(yawDeg: number, pitchDeg: number): Vec3 {
  const yaw = yawDeg * DEG;
  const pitch = pitchDeg * DEG;
  const cp = Math.cos(pitch);
  return [cp * Math.cos(yaw), cp * Math.sin(yaw), Math.sin(pitch)];
}

export function cross(a: Vec3, b: Vec3): Vec3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

export function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function norm(a: Vec3): number {
  return Math.hypot(a[0], a[1], a[2]);
}

export function normalize(a: Vec3): Vec3 {
  const n = norm(a);
  return [a[0] / n, a[1] / n, a[2] / n];
}

/**
 * The 4x4 camera-to-world pose of a viewpoint.
 *
 * Throws on a near-vertical pitch for the same reason the library does: with
 * the forward vector parallel to +Z the "right" axis is the cross product of
 * two parallel vectors, so the roll of the camera is undefined.
 */
export function cameraPose(position: Vec3, yawDeg: number, pitchDeg: number): Mat4 {
  if (Math.abs(pitchDeg) > 89.9) {
    throw new Error(
      `pitch ${pitchDeg} deg is too close to vertical, the camera roll is undefined`,
    );
  }
  if (position.length !== 3 || !position.every(Number.isFinite)) {
    throw new Error("position must be three finite coordinates");
  }

  const f = forwardVector(yawDeg, pitchDeg);
  const right = normalize(cross(f, [0, 0, 1]));
  const up = cross(right, f);

  return [
    [right[0], up[0], -f[0], position[0]],
    [right[1], up[1], -f[1], position[1]],
    [right[2], up[2], -f[2], position[2]],
    [0, 0, 0, 1],
  ];
}

/**
 * The viewport camera placement for a pose, mirroring `apply_pose` in the
 * desktop app: position, a focal point pushed `distance` along the view
 * direction, and the pose's own up axis.
 */
export function poseToView(pose: Mat4, distance: number) {
  const position: Vec3 = [pose[0][3], pose[1][3], pose[2][3]];
  const forward: Vec3 = [-pose[0][2], -pose[1][2], -pose[2][2]];
  const up: Vec3 = [pose[0][1], pose[1][1], pose[2][1]];
  const focal: Vec3 = [
    position[0] + forward[0] * distance,
    position[1] + forward[1] * distance,
    position[2] + forward[2] * distance,
  ];
  return { position, focal, up, forward };
}
