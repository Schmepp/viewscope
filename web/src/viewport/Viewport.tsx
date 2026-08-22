/**
 * React wrapper around SceneView, the counterpart of
 * QVTKRenderWindowInteractor inside QMainWindow.setCentralWidget.
 *
 * React never re-renders the 3D content; it only hands the scene new state
 * through effects, and the scene owns its own animation loop.
 */

import { useEffect, useRef } from "react";

import type { Bundle } from "../data/bundle";
import { SceneView, type Mode } from "./scene";

interface ViewportProps {
  bundle: Bundle | null;
  mode: Mode;
  pointSize: number;
  showGlyphs: boolean;
  scalars: { values: Float32Array; min: number; max: number } | null;
  cameraIndex: number | null;
  /** Bumped by the Overview action so a repeat click still recentres. */
  overviewNonce: number;
  onReady: () => void;
}

export function Viewport({
  bundle,
  mode,
  pointSize,
  showGlyphs,
  scalars,
  cameraIndex,
  overviewNonce,
  onReady,
}: ViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<SceneView | null>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  // Create once, and keep it alive for the life of the page: WebGL contexts
  // are a scarce resource and rebuilding one drops every GPU buffer.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const view = new SceneView(container);
    viewRef.current = view;

    const observer = new ResizeObserver(() => view.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      view.dispose();
      viewRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!bundle || !viewRef.current) return;
    viewRef.current.build(bundle);
    readyRef.current();
  }, [bundle]);

  useEffect(() => {
    viewRef.current?.setMode(mode);
  }, [mode, bundle]);

  useEffect(() => {
    viewRef.current?.setPointSize(pointSize);
  }, [pointSize, bundle]);

  useEffect(() => {
    viewRef.current?.setGlyphsVisible(showGlyphs);
  }, [showGlyphs, bundle]);

  useEffect(() => {
    if (!scalars) return;
    viewRef.current?.setScalarValues(scalars.values, scalars.min, scalars.max);
  }, [scalars, bundle]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !bundle) return;
    if (cameraIndex === null) view.showOverview();
    else view.showCamera(cameraIndex);
  }, [cameraIndex, overviewNonce, bundle]);

  return <div className="viewport" ref={containerRef} />;
}
