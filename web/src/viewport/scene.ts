/**
 * The viewport, standing in for vtkRenderer + QVTKRenderWindowInteractor.
 *
 * This is deliberately imperative and lives outside React, the same way the
 * desktop keeps its VTK actors outside the Qt widget tree: React owns the
 * panels and the state that drives them, and calls methods here to push that
 * state into GPU buffers. Re-rendering a 75k triangle mesh through a virtual
 * DOM diff would be the wrong shape entirely.
 *
 * Actor-for-actor mapping with vs_gui.py:
 *
 *     mesh_actor    -> this.mesh (+ this.wireframe for EdgeVisibilityOn)
 *     cloud_actor   -> this.cloud
 *     glyph_actors  -> this.glyphFaces + this.glyphEdges, merged into two
 *                      buffers because 185 separate actors is 370 draw calls
 *                      for 3k triangles
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { cameraGlyph, GLYPH_TEMPLATE } from "../core/glyph";
import { colorize } from "../core/lut";
import { cameraPose, poseToView, type Vec3 } from "../core/pose";
import type { Bundle, Viewpoint } from "../data/bundle";

export const MODE_TEXTURED = "Textured mesh";
export const MODE_GEOMETRY = "Geometry (.obj)";
export const MODE_TARGETS = "Target values";
export const MODE_ALL = "All three";
export const MODES = [MODE_TEXTURED, MODE_GEOMETRY, MODE_TARGETS, MODE_ALL] as const;
export type Mode = (typeof MODES)[number];

const YFOV_DEG = 53.1301;
const BACKGROUND = 0x080810; // renderer.SetBackground(0.03, 0.03, 0.05)

interface CameraState {
  position: THREE.Vector3;
  target: THREE.Vector3;
  up: THREE.Vector3;
  fov: number;
}

export class SceneView {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;

  private mesh: THREE.Mesh | null = null;
  private wireframe: THREE.LineSegments | null = null;
  private cloud: THREE.Points | null = null;
  private glyphFaces: THREE.Mesh | null = null;
  private glyphEdges: THREE.LineSegments | null = null;

  /** Placed marker vertices per viewpoint, computed once at load. */
  private glyphVertices: Float32Array[] = [];
  private viewpoints: Viewpoint[] = [];

  private cloudColors: Float32Array | null = null;
  private meshVertexColors: THREE.BufferAttribute | null = null;

  diagonal = 1;
  private mode: Mode = MODE_ALL;
  private showGlyphs = true;
  private cameraIndex: number | null = null;
  private overviewState: CameraState | null = null;

  private frame = 0;
  private disposed = false;

  constructor(private readonly container: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(BACKGROUND, 1);
    container.appendChild(this.renderer.domElement);

    this.scene.background = new THREE.Color(BACKGROUND);

    this.camera = new THREE.PerspectiveCamera(YFOV_DEG, 1, 0.1, 5000);
    // One world frame everywhere: right handed, +Z up.
    this.camera.up.set(0, 0, 1);
    this.scene.add(this.camera);

    // vtkRenderer creates a headlight by default: a light that sits on the
    // camera and shines down the view direction. Parenting to the camera
    // reproduces that.
    this.camera.add(new THREE.DirectionalLight(0xffffff, 2.2));
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    // vtkInteractorStyleTrackballCamera: left drag orbits, middle drag pans,
    // scroll zooms. Right drag pans too, since browsers have no middle button
    // on a trackpad.
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.PAN,
      RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };

    this.resize();
    this.animate();
  }

  // ----------------------------------------------------------------------
  // construction, mirroring MainWindow.on_loaded
  // ----------------------------------------------------------------------

  build(bundle: Bundle): void {
    const { manifest } = bundle;
    this.diagonal = manifest.mesh.diagonal;
    this.viewpoints = manifest.plan.viewpoints;

    this.buildMesh(bundle);
    this.buildCloud(bundle);
    this.buildGlyphs(manifest.plan.viewpoints);

    this.resetCamera(manifest.mesh.bounds);
    this.saveOverview();
    this.setMode(this.mode);
  }

  private buildMesh(bundle: Bundle): void {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(bundle.mesh.positions, 3));
    geometry.setIndex(new THREE.BufferAttribute(bundle.mesh.indices, 1));

    if (bundle.mesh.colors) {
      // Normalised uint8 straight from trimesh's vertex_colors, no copy.
      this.meshVertexColors = new THREE.BufferAttribute(bundle.mesh.colors, 3, true);
      geometry.setAttribute("color", this.meshVertexColors);
    }
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();

    const material = new THREE.MeshLambertMaterial({
      vertexColors: this.meshVertexColors !== null,
      color: 0xffffff,
      side: THREE.DoubleSide, // the scan surface is not closed
    });
    this.mesh = new THREE.Mesh(geometry, material);
    this.scene.add(this.mesh);
  }

  private buildCloud(bundle: Bundle): void {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(bundle.targets, 3));
    this.cloudColors = new Float32Array((bundle.targets.length / 3) * 3);
    geometry.setAttribute("color", new THREE.BufferAttribute(this.cloudColors, 3));
    geometry.computeBoundingSphere();

    const material = new THREE.PointsMaterial({
      size: 2 * this.renderer.getPixelRatio(),
      sizeAttenuation: false, // vtkProperty point size is in device pixels
      vertexColors: true,
    });
    this.cloud = new THREE.Points(geometry, material);
    this.scene.add(this.cloud);
  }

  /**
   * All 185 markers merged into one triangle buffer and one line buffer.
   *
   * Face colours from the library are per triangle, so the geometry is
   * unindexed: three vertices per triangle, each carrying its face's colour.
   */
  private buildGlyphs(viewpoints: Viewpoint[]): void {
    const template = GLYPH_TEMPLATE;
    const triangles = template.faces.length / 3;
    const segments = template.edges.length / 2;
    const n = viewpoints.length;

    this.glyphVertices = viewpoints.map((vp) =>
      cameraGlyph(vp.position as Vec3, vp.yaw_deg, vp.pitch_deg),
    );

    const facePositions = new Float32Array(n * triangles * 3 * 3);
    const faceColors = new Float32Array(n * triangles * 3 * 3);
    const edgePositions = new Float32Array(n * segments * 2 * 3);

    const faceGeometry = new THREE.BufferGeometry();
    faceGeometry.setAttribute("position", new THREE.BufferAttribute(facePositions, 3));
    faceGeometry.setAttribute("color", new THREE.BufferAttribute(faceColors, 3));

    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute("position", new THREE.BufferAttribute(edgePositions, 3));

    // Colours never change, so fill them for every slot up front; only the
    // positions and the draw range move when the hidden marker changes.
    for (let slot = 0; slot < n; slot++) {
      for (let t = 0; t < triangles; t++) {
        const [r, g, b] = [
          template.faceColors[t * 3] / 255,
          template.faceColors[t * 3 + 1] / 255,
          template.faceColors[t * 3 + 2] / 255,
        ];
        for (let c = 0; c < 3; c++) {
          const v = (slot * triangles + t) * 3 + c;
          faceColors[v * 3] = r;
          faceColors[v * 3 + 1] = g;
          faceColors[v * 3 + 2] = b;
        }
      }
    }

    this.glyphFaces = new THREE.Mesh(
      faceGeometry,
      new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }),
    );
    this.glyphEdges = new THREE.LineSegments(
      edgeGeometry,
      // vtkProperty.SetLineWidth(2.0); most WebGL drivers clamp this to 1.
      new THREE.LineBasicMaterial({ color: 0x0b1a1a, linewidth: 2 }),
    );
    this.scene.add(this.glyphFaces, this.glyphEdges);
    this.refreshGlyphs();
  }

  // ----------------------------------------------------------------------
  // display state, mirroring MainWindow.set_* slots
  // ----------------------------------------------------------------------

  setMode(mode: Mode): void {
    this.mode = mode;
    if (!this.mesh || !this.cloud) return;

    const showMesh =
      mode === MODE_TEXTURED || mode === MODE_GEOMETRY || mode === MODE_ALL;
    const showCloud = mode === MODE_TARGETS || mode === MODE_ALL;

    this.mesh.visible = showMesh;
    this.cloud.visible = showCloud;

    const material = this.mesh.material as THREE.MeshLambertMaterial;
    if (mode === MODE_GEOMETRY) {
      // Raw tessellation: flat grey, no vertex colours, every cell edge drawn.
      material.vertexColors = false;
      material.color.setRGB(0.62, 0.64, 0.7);
      this.ensureWireframe();
      if (this.wireframe) this.wireframe.visible = true;
    } else if (showMesh) {
      material.vertexColors = this.meshVertexColors !== null;
      material.color.setRGB(1, 1, 1);
      if (this.wireframe) this.wireframe.visible = false;
    } else if (this.wireframe) {
      this.wireframe.visible = false;
    }
    material.needsUpdate = true;
    this.invalidate();
  }

  /**
   * Built lazily: 150k triangles expand to 450k line segments, which is a
   * 10 MB buffer nobody should pay for unless they open Geometry mode.
   */
  private ensureWireframe(): void {
    if (this.wireframe || !this.mesh) return;
    const geometry = new THREE.WireframeGeometry(this.mesh.geometry);
    this.wireframe = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color: new THREE.Color(0.15, 0.16, 0.2) }),
    );
    this.scene.add(this.wireframe);
  }

  setScalarValues(values: Float32Array, min: number, max: number): void {
    if (!this.cloud || !this.cloudColors) return;
    colorize(values, min, max, this.cloudColors);
    (this.cloud.geometry.getAttribute("color") as THREE.BufferAttribute).needsUpdate = true;
    this.invalidate();
  }

  setPointSize(size: number): void {
    if (!this.cloud) return;
    (this.cloud.material as THREE.PointsMaterial).size =
      size * this.renderer.getPixelRatio();
    this.invalidate();
  }

  setGlyphsVisible(visible: boolean): void {
    this.showGlyphs = visible;
    this.refreshGlyphs();
  }

  /**
   * Repack the merged buffers, skipping the marker for the viewpoint the
   * camera is currently sitting inside: drawn, it would fill the whole view.
   */
  private refreshGlyphs(): void {
    if (!this.glyphFaces || !this.glyphEdges) return;

    const visible = this.showGlyphs;
    this.glyphFaces.visible = visible;
    this.glyphEdges.visible = visible;
    if (!visible) {
      this.invalidate();
      return;
    }

    const template = GLYPH_TEMPLATE;
    const triangles = template.faces.length / 3;
    const segments = template.edges.length / 2;
    const facePositions = this.glyphFaces.geometry.getAttribute(
      "position",
    ) as THREE.BufferAttribute;
    const edgePositions = this.glyphEdges.geometry.getAttribute(
      "position",
    ) as THREE.BufferAttribute;
    const faceArray = facePositions.array as Float32Array;
    const edgeArray = edgePositions.array as Float32Array;

    let faceCursor = 0;
    let edgeCursor = 0;
    for (let i = 0; i < this.glyphVertices.length; i++) {
      if (i === this.cameraIndex) continue;
      const verts = this.glyphVertices[i];
      for (let t = 0; t < triangles * 3; t++) {
        const v = template.faces[t] * 3;
        faceArray[faceCursor++] = verts[v];
        faceArray[faceCursor++] = verts[v + 1];
        faceArray[faceCursor++] = verts[v + 2];
      }
      for (let e = 0; e < segments * 2; e++) {
        const v = template.edges[e] * 3;
        edgeArray[edgeCursor++] = verts[v];
        edgeArray[edgeCursor++] = verts[v + 1];
        edgeArray[edgeCursor++] = verts[v + 2];
      }
    }

    facePositions.needsUpdate = true;
    edgePositions.needsUpdate = true;
    this.glyphFaces.geometry.setDrawRange(0, faceCursor / 3);
    this.glyphEdges.geometry.setDrawRange(0, edgeCursor / 3);
    this.glyphFaces.geometry.computeBoundingSphere();
    this.invalidate();
  }

  // ----------------------------------------------------------------------
  // camera flipping, mirroring show_camera / show_overview
  // ----------------------------------------------------------------------

  /**
   * Frame the whole bundle, standing in for vtkRenderer.ResetCamera.
   *
   * VTK inherits its default view direction from the untouched vtkCamera,
   * which for a +Z up scene means looking straight down. That is a gimbal
   * singularity for an orbit controller, so the overview is pitched off the
   * pole into a three-quarter view instead.
   */
  private resetCamera(bounds: [Vec3, Vec3]): void {
    const min = new THREE.Vector3(...bounds[0]);
    const max = new THREE.Vector3(...bounds[1]);
    const center = min.clone().add(max).multiplyScalar(0.5);
    const radius = max.clone().sub(min).length() * 0.5;
    const distance = radius / Math.sin((YFOV_DEG * Math.PI) / 180 / 2);

    const direction = new THREE.Vector3(-0.55, -0.62, 0.56).normalize();
    this.camera.up.set(0, 0, 1);
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.camera.fov = YFOV_DEG;
    this.controls.target.copy(center);
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  private saveOverview(): void {
    this.overviewState = {
      position: this.camera.position.clone(),
      target: this.controls.target.clone(),
      up: this.camera.up.clone(),
      fov: this.camera.fov,
    };
  }

  showOverview(): void {
    if (this.overviewState) {
      this.camera.position.copy(this.overviewState.position);
      this.controls.target.copy(this.overviewState.target);
      this.camera.up.copy(this.overviewState.up);
      this.camera.fov = this.overviewState.fov;
      this.camera.updateProjectionMatrix();
      this.controls.update();
    } else {
      this.saveOverview();
    }
    this.cameraIndex = null;
    this.refreshGlyphs();
  }

  showCamera(index: number): void {
    const n = this.viewpoints.length;
    if (n === 0) return;

    // The first jump away from the overview banks it, so Overview returns to
    // wherever the user had orbited to rather than the initial framing.
    if (this.cameraIndex === null) this.saveOverview();

    this.cameraIndex = ((index % n) + n) % n;
    const vp = this.viewpoints[this.cameraIndex];
    const { position, focal, up } = poseToView(
      cameraPose(vp.position as Vec3, vp.yaw_deg, vp.pitch_deg),
      this.diagonal,
    );

    this.camera.up.set(...up);
    this.camera.position.set(...position);
    this.controls.target.set(...focal);
    this.camera.fov = YFOV_DEG;
    this.camera.updateProjectionMatrix();
    this.controls.update();

    this.refreshGlyphs();
  }

  get currentCamera(): number | null {
    return this.cameraIndex;
  }

  // ----------------------------------------------------------------------

  resize(): void {
    const width = this.container.clientWidth || 1;
    const height = this.container.clientHeight || 1;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.invalidate();
  }

  /** Nudge the render loop; damping means it keeps going for a few frames. */
  private invalidate(): void {
    this.controls.update();
  }

  private animate = (): void => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.animate);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.controls.dispose();
    this.scene.traverse((object) => {
      const any = object as THREE.Mesh;
      any.geometry?.dispose?.();
      const material = any.material;
      if (Array.isArray(material)) material.forEach((m) => m.dispose());
      else material?.dispose?.();
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
