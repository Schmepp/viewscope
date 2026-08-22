/** Port of DisplayPanel: display mode, scalar field, point size, glyphs. */

import { MODES, type Mode } from "../viewport/scene";
import { SCALAR_FIELDS, type ScalarField } from "../data/bundle";
import { cssGradient } from "../core/lut";

interface DisplayPanelProps {
  mode: Mode;
  onMode: (mode: Mode) => void;
  field: ScalarField;
  onField: (field: ScalarField) => void;
  fieldsEnabled: boolean;
  pointSize: number;
  onPointSize: (size: number) => void;
  showGlyphs: boolean;
  onShowGlyphs: (visible: boolean) => void;
  range: { min: number; max: number } | null;
}

export function DisplayPanel({
  mode,
  onMode,
  field,
  onField,
  fieldsEnabled,
  pointSize,
  onPointSize,
  showGlyphs,
  onShowGlyphs,
  range,
}: DisplayPanelProps) {
  return (
    <>
      <fieldset className="group">
        <legend>Scene</legend>

        <label className="row">
          <span>Display</span>
          <select value={mode} onChange={(e) => onMode(e.target.value as Mode)}>
            {MODES.map((option, i) => (
              <option key={option} value={option}>
                {i + 1}. {option}
              </option>
            ))}
          </select>
        </label>

        <label className="row">
          <span>Colour by</span>
          <select
            value={field}
            disabled={!fieldsEnabled}
            onChange={(e) => onField(e.target.value as ScalarField)}
          >
            {SCALAR_FIELDS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label className="row">
          <span>Point size</span>
          <span className="slider">
            <input
              type="range"
              min={1}
              max={10}
              step={1}
              value={pointSize}
              onChange={(e) => onPointSize(Number(e.target.value))}
            />
            <output>{pointSize}</output>
          </span>
        </label>

        <label className="row row-check">
          <input
            type="checkbox"
            checked={showGlyphs}
            onChange={(e) => onShowGlyphs(e.target.checked)}
          />
          <span>Show camera frusta</span>
        </label>
      </fieldset>

      {/* vtkScalarBarActor, drawn in the panel instead of over the viewport. */}
      {fieldsEnabled && range && (
        <fieldset className="group">
          <legend>{field}</legend>
          <div className="scalar-bar">
            <div className="scalar-ramp" style={{ background: cssGradient() }} />
            <div className="scalar-ticks">
              {[1, 0.75, 0.5, 0.25, 0].map((t) => (
                <span key={t}>{(range.min + (range.max - range.min) * t).toFixed(3)}</span>
              ))}
            </div>
          </div>
        </fieldset>
      )}
    </>
  );
}
