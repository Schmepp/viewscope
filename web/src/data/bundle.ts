/**
 * Fetches the exported bundle.
 *
 * The desktop app does this on a QThread (LoaderThread) so the interface
 * stays responsive while trimesh parses the scan. In the browser fetch is
 * already asynchronous, so the equivalent is just an async function that
 * reports progress the same way LoaderThread.progress did.
 */

import type { Vec3 } from "../core/pose";

export const SCALAR_FIELDS = ["score_8", "score_4", "diversity_8", "diversity_4"] as const;
export type ScalarField = (typeof SCALAR_FIELDS)[number];

export interface Viewpoint {
  id: string;
  position: Vec3;
  yaw_deg: number;
  pitch_deg: number;
}

interface BlobEntry {
  file: string;
  dtype: string;
  count: number;
  components: number;
  bytes: number;
}

interface FieldEntry extends BlobEntry {
  min: number;
  mean: number;
  max: number;
}

export interface Manifest {
  version: number;
  mesh: {
    positions: BlobEntry;
    indices: BlobEntry;
    colors: BlobEntry | null;
    vertexCount: number;
    triangleCount: number;
    bounds: [Vec3, Vec3];
    diagonal: number;
    visualKind: string | null;
  };
  targets: { positions: BlobEntry; normals: BlobEntry; count: number };
  plan: {
    camera: { width: number; height: number; yfov_deg: number };
    count: number;
    viewpoints: Viewpoint[];
  };
  scores: { fields: Record<ScalarField, FieldEntry>; order: ScalarField[] } | null;
  scoresError: string | null;
}

export interface Bundle {
  manifest: Manifest;
  mesh: {
    positions: Float32Array;
    indices: Uint32Array;
    colors: Uint8Array | null;
  };
  targets: Float32Array;
  fields: Record<string, Float32Array>;
}

const BASE = "data";

async function fetchBinary(entry: BlobEntry): Promise<ArrayBuffer> {
  const response = await fetch(`${BASE}/${entry.file}`);
  if (!response.ok) {
    throw new Error(`${entry.file}: ${response.status} ${response.statusText}`);
  }
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength !== entry.bytes) {
    // Fail closed, like viewscope_core's loaders: a short read means a
    // truncated deploy, and silently rendering half a mesh hides that.
    throw new Error(
      `${entry.file}: expected ${entry.bytes} bytes, received ${buffer.byteLength}`,
    );
  }
  return buffer;
}

export async function loadBundle(onProgress: (message: string) => void): Promise<Bundle> {
  onProgress("Loading manifest...");
  const manifestResponse = await fetch(`${BASE}/manifest.json`);
  if (!manifestResponse.ok) {
    throw new Error(
      `manifest.json: ${manifestResponse.status} ${manifestResponse.statusText}`,
    );
  }
  const manifest: Manifest = await manifestResponse.json();

  onProgress("Loading scene mesh...");
  const [positions, indices, colors] = await Promise.all([
    fetchBinary(manifest.mesh.positions),
    fetchBinary(manifest.mesh.indices),
    manifest.mesh.colors ? fetchBinary(manifest.mesh.colors) : Promise.resolve(null),
  ]);

  onProgress("Loading targets...");
  const targets = await fetchBinary(manifest.targets.positions);

  onProgress("Loading scores...");
  const fields: Record<string, Float32Array> = {};
  if (manifest.scores) {
    const names = manifest.scores.order;
    const buffers = await Promise.all(
      names.map((name) => fetchBinary(manifest.scores!.fields[name])),
    );
    names.forEach((name, i) => {
      fields[name] = new Float32Array(buffers[i]);
    });
  }

  return {
    manifest,
    mesh: {
      positions: new Float32Array(positions),
      indices: new Uint32Array(indices),
      colors: colors ? new Uint8Array(colors) : null,
    },
    targets: new Float32Array(targets),
    fields,
  };
}
