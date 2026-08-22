/**
 * ViewScope, the browser build.
 *
 * A port of src/viewscope/vs_gui.py: the same viewport, the same three docks,
 * the same toolbar, menus, shortcuts and status line, with QMainWindow's job
 * done by CSS grid and QSettings' job done by localStorage.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Dock, Splitter } from "./panels/Dock";
import { DisplayPanel } from "./panels/DisplayPanel";
import { MetricsPanel } from "./panels/MetricsPanel";
import { ViewpointPanel } from "./panels/ViewpointPanel";
import { Viewport } from "./viewport/Viewport";
import { MODES, MODE_ALL, type Mode } from "./viewport/scene";
import { loadBundle, SCALAR_FIELDS, type Bundle, type ScalarField } from "./data/bundle";
import { useLayout, type PanelId } from "./hooks/useLayout";

const PANEL_TITLES: Record<PanelId, string> = {
  viewpoints: "Viewpoints",
  display: "Display",
  metrics: "Metrics",
};

const count = (value: number) => value.toLocaleString("en-US");

export default function App() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [status, setStatus] = useState("Loading...");
  const [error, setError] = useState<string | null>(null);

  const [mode, setMode] = useState<Mode>(MODE_ALL);
  const [field, setField] = useState<ScalarField>("score_8");
  const [pointSize, setPointSize] = useState(2);
  const [showGlyphs, setShowGlyphs] = useState(true);
  const [cameraIndex, setCameraIndex] = useState<number | null>(null);
  const [overviewNonce, setOverviewNonce] = useState(0);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);

  const { layout, togglePanel, setWidth, reset } = useLayout();

  // ---- loading, standing in for LoaderThread ---------------------------
  useEffect(() => {
    let cancelled = false;
    loadBundle((message) => !cancelled && setStatus(message))
      .then((loaded) => {
        if (cancelled) return;
        setBundle(loaded);
        if (!loaded.manifest.scores && loaded.manifest.scoresError) {
          console.warn(`scores unavailable: ${loaded.manifest.scoresError}`);
        }
      })
      .catch((exc: unknown) => {
        if (cancelled) return;
        setStatus("Load failed");
        setError(exc instanceof Error ? `${exc.name}: ${exc.message}` : String(exc));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const manifest = bundle?.manifest ?? null;
  const viewpoints = manifest?.plan.viewpoints ?? [];
  const scoresAvailable = Boolean(manifest?.scores);
  const fieldStats = manifest?.scores?.fields[field] ?? null;

  const scalars = useMemo(() => {
    if (!bundle || !fieldStats) return null;
    return { values: bundle.fields[field], min: fieldStats.min, max: fieldStats.max };
  }, [bundle, field, fieldStats]);

  // ---- camera flipping, mirroring next_camera / prev_camera ------------
  const showCamera = useCallback(
    (index: number) => {
      const n = viewpoints.length;
      if (n === 0) return;
      const wrapped = ((index % n) + n) % n;
      setCameraIndex(wrapped);
      setStatus(`Camera ${wrapped + 1} of ${n}`);
    },
    [viewpoints.length],
  );

  const showOverview = useCallback(() => {
    setCameraIndex(null);
    setOverviewNonce((n) => n + 1);
    setStatus("Overview");
  }, []);

  // Read through a ref so the key handler is bound once and never re-attached.
  const indexRef = useRef(cameraIndex);
  indexRef.current = cameraIndex;

  const nextCamera = useCallback(
    () => showCamera(indexRef.current === null ? 0 : indexRef.current + 1),
    [showCamera],
  );
  const prevCamera = useCallback(
    () => showCamera(indexRef.current === null ? -1 : indexRef.current - 1),
    [showCamera],
  );

  // ---- shortcuts, mirroring the QAction shortcuts ----------------------
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      // Held keys auto-repeat, which would skip a dozen viewpoints per press.
      if (event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;

      switch (event.key) {
        case "n":
        case "ArrowRight":
          nextCamera();
          break;
        case "p":
        case "ArrowLeft":
          prevCamera();
          break;
        case "o":
          showOverview();
          break;
        case "1":
        case "2":
        case "3":
        case "4":
          setMode(MODES[Number(event.key) - 1]);
          break;
        case "Escape":
          setMenuOpen(null);
          return;
        default:
          return;
      }
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nextCamera, prevCamera, showOverview]);

  const onViewportReady = useCallback(() => setStatus("Ready"), []);

  // ---- metrics ---------------------------------------------------------
  const metrics = useMemo(() => {
    const dash = "--";
    const selected = cameraIndex !== null ? viewpoints[cameraIndex] : null;
    return [
      {
        title: "Bundle",
        rows: [
          ["Vertices", manifest ? count(manifest.mesh.vertexCount) : dash],
          ["Triangles", manifest ? count(manifest.mesh.triangleCount) : dash],
          ["Diagonal", manifest ? manifest.mesh.diagonal.toFixed(2) : dash],
          ["Targets", manifest ? count(manifest.targets.count) : dash],
          ["Cameras", manifest ? count(manifest.plan.count) : dash],
        ] as Array<[string, string]>,
      },
      {
        title: "Scalar field",
        rows: [
          ["Field", scoresAvailable ? field : "unavailable"],
          ["Min", fieldStats ? fieldStats.min.toFixed(4) : dash],
          ["Mean", fieldStats ? fieldStats.mean.toFixed(4) : dash],
          ["Max", fieldStats ? fieldStats.max.toFixed(4) : dash],
        ] as Array<[string, string]>,
      },
      {
        title: "Viewpoint",
        rows: [
          ["Camera", selected ? `${cameraIndex! + 1} of ${viewpoints.length}` : dash],
          [
            "Position",
            selected
              ? selected.position.map((c) => c.toFixed(2)).join(", ")
              : dash,
          ],
          ["Yaw", selected ? selected.yaw_deg.toFixed(2) : dash],
          ["Pitch", selected ? selected.pitch_deg.toFixed(2) : dash],
        ] as Array<[string, string]>,
      },
    ];
  }, [manifest, scoresAvailable, field, fieldStats, cameraIndex, viewpoints]);

  const leftOpen = layout.visible.viewpoints;
  const rightOpen = layout.visible.display || layout.visible.metrics;

  return (
    <div className="window" onPointerDown={() => menuOpen && setMenuOpen(null)}>
      <div className="menubar">
        <strong className="brand">ViewScope</strong>

        <Menu
          label="View"
          open={menuOpen === "view"}
          onToggle={() => setMenuOpen(menuOpen === "view" ? null : "view")}
        >
          {(Object.keys(PANEL_TITLES) as PanelId[]).map((id) => (
            <button key={id} type="button" onClick={() => togglePanel(id)}>
              <span className="tick">{layout.visible[id] ? "✓" : ""}</span>
              {PANEL_TITLES[id]}
            </button>
          ))}
          <hr />
          <button type="button" onClick={reset}>
            <span className="tick" />
            Reset layout
          </button>
        </Menu>

        <Menu
          label="Camera"
          open={menuOpen === "camera"}
          onToggle={() => setMenuOpen(menuOpen === "camera" ? null : "camera")}
        >
          <button type="button" onClick={prevCamera}>
            <span className="tick" />
            Previous <kbd>P</kbd>
          </button>
          <button type="button" onClick={nextCamera}>
            <span className="tick" />
            Next <kbd>N</kbd>
          </button>
          <button type="button" onClick={showOverview}>
            <span className="tick" />
            Overview <kbd>O</kbd>
          </button>
        </Menu>

        <div className="toolbar">
          <button type="button" onClick={prevCamera} disabled={!bundle}>
            Previous
          </button>
          <button type="button" onClick={nextCamera} disabled={!bundle}>
            Next
          </button>
          <button type="button" onClick={showOverview} disabled={!bundle}>
            Overview
          </button>
        </div>

        <span className="hint">
          drag to orbit · right drag to pan · scroll to zoom
        </span>
      </div>

      <div className="body">
        {leftOpen && (
          <>
            <aside className="rail" style={{ width: layout.leftWidth }}>
              <Dock title="Viewpoints" onClose={() => togglePanel("viewpoints")} flush>
                <ViewpointPanel
                  viewpoints={viewpoints}
                  selected={cameraIndex}
                  onSelect={showCamera}
                />
              </Dock>
            </aside>
            <Splitter
              side="left"
              width={layout.leftWidth}
              onResize={(value) => setWidth("leftWidth", value)}
            />
          </>
        )}

        <main className="stage">
          <Viewport
            bundle={bundle}
            mode={mode}
            pointSize={pointSize}
            showGlyphs={showGlyphs}
            scalars={scalars}
            cameraIndex={cameraIndex}
            overviewNonce={overviewNonce}
            onReady={onViewportReady}
          />
          {!bundle && !error && <div className="overlay">{status}</div>}
          {error && (
            <div className="overlay overlay-error">
              <h2>Could not load the bundle.</h2>
              <p>{error}</p>
              <p className="muted">
                Run <code>npm run export-data</code> from <code>web/</code> to
                regenerate <code>public/data</code>.
              </p>
            </div>
          )}
        </main>

        {rightOpen && (
          <>
            <Splitter
              side="right"
              width={layout.rightWidth}
              onResize={(value) => setWidth("rightWidth", value)}
            />
            <aside className="rail" style={{ width: layout.rightWidth }}>
              {layout.visible.display && (
                <Dock title="Display" onClose={() => togglePanel("display")}>
                  <DisplayPanel
                    mode={mode}
                    onMode={setMode}
                    field={field}
                    onField={setField}
                    fieldsEnabled={scoresAvailable}
                    pointSize={pointSize}
                    onPointSize={setPointSize}
                    showGlyphs={showGlyphs}
                    onShowGlyphs={setShowGlyphs}
                    range={fieldStats}
                  />
                </Dock>
              )}
              {layout.visible.metrics && (
                <Dock title="Metrics" onClose={() => togglePanel("metrics")}>
                  <MetricsPanel groups={metrics} />
                </Dock>
              )}
            </aside>
          </>
        )}
      </div>

      <footer className="statusbar">
        <span>{status}</span>
        <span className="muted">
          {manifest
            ? `${count(manifest.plan.count)} viewpoints · ${count(
                manifest.targets.count,
              )} targets · ${SCALAR_FIELDS.length} scalar fields`
            : ""}
        </span>
      </footer>
    </div>
  );
}

function Menu({
  label,
  open,
  onToggle,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="menu" onPointerDown={(e) => e.stopPropagation()}>
      <button type="button" className={open ? "menu-label open" : "menu-label"} onClick={onToggle}>
        {label}
      </button>
      {open && (
        <div className="menu-popup" onClick={onToggle}>
          {children}
        </div>
      )}
    </div>
  );
}
