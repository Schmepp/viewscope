/**
 * Port of viewscope_core.glyph: the standard viewpoint marker.
 *
 * A little camera body with a lens cone, rotated to face the way the
 * viewpoint faces and dropped at its position. The template is identical for
 * every viewpoint, so it is built once and only the 3x3 rotation changes.
 */

import { cross, dot, forwardVector, norm, type Vec3 } from "./pose";

export type Mat3 = number[][];

export interface GlyphTemplate {
  /** 10 vertices, flat xyz. */
  vertices: Float64Array;
  /** 16 triangles, flat indices. */
  faces: Uint32Array;
  /** One rgb per triangle: 12 body, 4 lens. */
  faceColors: Uint8Array;
  /** 16 wireframe segments, flat index pairs. */
  edges: Uint32Array;
}

const ASPECT = 1368.0 / 912.0;

function buildTemplate(): GlyphTemplate {
  const v = [
    [1, 1, 1], [-1, 1, 1], [-1, -1, 1], [1, -1, 1],
    [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, -1],
    [0, 0, 1.5], [0, 0, 0],
  ].map((row) => row.slice());

  for (let i = 0; i < 4; i++) v[i][0] *= ASPECT;
  for (let i = 0; i < 4; i++) for (let c = 0; c < 3; c++) v[i][c] *= 0.4;
  for (let i = 4; i < 8; i++) v[i][0] *= ASPECT;
  for (let i = 0; i < 10; i++) v[i][2] *= 0.7;

  // Recentre on the centroid so the marker straddles its position.
  const mean = [0, 1, 2].map((c) => v.reduce((s, row) => s + row[c], 0) / v.length);
  for (const row of v) for (let c = 0; c < 3; c++) row[c] -= mean[c];

  const groups = [
    [0, 1, 3, 1, 2, 3], [0, 3, 4, 0, 4, 5], [0, 5, 1, 1, 5, 6],
    [1, 6, 2, 2, 6, 7], [2, 7, 3, 3, 7, 4], [4, 7, 5, 5, 7, 6],
    [0, 1, 8, 1, 2, 8], [2, 3, 8, 3, 0, 8],
  ];
  const faces: number[] = [];
  for (const g of groups) for (const i of [0, 3]) faces.push(g[i], g[i + 1], g[i + 2]);

  const body = [26, 230, 230];
  const lens = [255, 31, 31];
  const faceColors: number[] = [];
  for (let i = 0; i < 12; i++) faceColors.push(...body);
  for (let i = 0; i < 4; i++) faceColors.push(...lens);

  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 5], [1, 6], [2, 7], [3, 4], [0, 8], [1, 8], [2, 8], [3, 8],
  ].flat();

  return {
    vertices: Float64Array.from(v.flat()),
    faces: Uint32Array.from(faces),
    faceColors: Uint8Array.from(faceColors),
    edges: Uint32Array.from(edges),
  };
}

export const GLYPH_TEMPLATE = buildTemplate();

/** Rodrigues rotation taking unit vector `a` onto unit vector `b`. */
function rotationBetween(a: Vec3, b: Vec3): Mat3 {
  const u = a.map((x) => x / norm(a)) as Vec3;
  const w = b.map((x) => x / norm(b)) as Vec3;
  const c = cross(u, w);
  const d = dot(u, w);
  const k: Mat3 = [
    [0, -c[2], c[1]],
    [c[2], 0, -c[0]],
    [-c[1], c[0], 0],
  ];
  const kk = matmul3(k, k);
  const s = (1.0 - d) / (norm(c) ** 2);
  const out: Mat3 = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      out[i][j] = (i === j ? 1 : 0) + k[i][j] + kk[i][j] * s;
    }
  }
  return out;
}

function matmul3(a: Mat3, b: Mat3): Mat3 {
  const out: Mat3 = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      out[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
    }
  }
  return out;
}

/**
 * The 'rxzx' Euler composition the library uses, kept in its transposed,
 * axis-swapped form so the result matches numpy element for element.
 */
function eulerRxzx(angleI: number, angleJ: number, angleK: number): Mat3 {
  const i = 0, j = 2, k = 1;
  [angleI, angleK] = [angleK, angleI];
  angleI = -angleI;
  angleJ = -angleJ;
  angleK = -angleK;

  const si = Math.sin(angleI), sj = Math.sin(angleJ), sk = Math.sin(angleK);
  const ci = Math.cos(angleI), cj = Math.cos(angleJ), ck = Math.cos(angleK);

  const m: Mat3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  m[i][i] = cj;
  m[i][j] = sj * si;
  m[i][k] = sj * ci;
  m[j][i] = sj * sk;
  m[j][j] = -cj * si * sk + ci * ck;
  m[j][k] = -cj * ci * sk - si * ck;
  m[k][i] = -sj * ck;
  m[k][j] = cj * si * ck + ci * sk;
  m[k][k] = cj * ci * ck - si * sk;
  return m;
}

function transpose3(m: Mat3): Mat3 {
  return [
    [m[0][0], m[1][0], m[2][0]],
    [m[0][1], m[1][1], m[2][1]],
    [m[0][2], m[1][2], m[2][2]],
  ];
}

// The template points down +Z; the library first swings it onto -Y and then
// applies heading and pitch. Constant, so compute it once.
const INITIAL = rotationBetween([0, 0, 1], [0, -1, 0]);

const DEG = Math.PI / 180;

/** The 3x3 world rotation of a viewpoint's marker. */
export function glyphRotation(yawDeg: number, pitchDeg: number): Mat3 {
  const heading = ((90.0 - yawDeg) % 360.0 + 360.0) % 360.0;
  const rotation = matmul3(
    transpose3(eulerRxzx(-pitchDeg * DEG, heading * DEG, 0.0)),
    INITIAL,
  );

  // Same self-check as the library: the marker must agree with the analytic
  // forward vector, otherwise the plan would be drawn facing the wrong way.
  const gf: Vec3 = [rotation[0][2] * -1, rotation[1][2] * -1, rotation[2][2] * -1];
  const expected = forwardVector(yawDeg, pitchDeg);
  if (dot(gf, expected) < 1.0 - 1e-9) {
    throw new Error("glyph orientation disagrees with forward_vector");
  }
  return rotation;
}

/**
 * Placed marker vertices for one viewpoint, flat xyz.
 * Equivalent to `vc.camera_glyph(position, yaw, pitch)[0]`.
 */
export function cameraGlyph(
  position: Vec3,
  yawDeg: number,
  pitchDeg: number,
  scale = 0.5,
): Float32Array {
  const r = glyphRotation(yawDeg, pitchDeg);
  const t = GLYPH_TEMPLATE.vertices;
  const out = new Float32Array(t.length);
  for (let v = 0; v < t.length / 3; v++) {
    const x = t[v * 3], y = t[v * 3 + 1], z = t[v * 3 + 2];
    for (let c = 0; c < 3; c++) {
      out[v * 3 + c] =
        (r[c][0] * x + r[c][1] * y + r[c][2] * z) * scale + position[c];
    }
  }
  return out;
}
