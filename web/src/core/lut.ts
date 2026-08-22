/**
 * The colour table the desktop app builds with
 *
 *     lut = vtk.vtkLookupTable()
 *     lut.SetHueRange(0.667, 0.0)   # blue low, red high
 *
 * vtkLookupTable sweeps hue linearly with saturation and value pinned at 1,
 * which is the classic rainbow ramp. Reproduced here so the point cloud and
 * the colour legend agree with the screenshots from the Qt build.
 */

export const HUE_LOW = 0.667;
export const HUE_HIGH = 0.0;

/** HSV to RGB, each channel in 0..1. */
export function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, t, p];
    case 1: return [q, v, p];
    case 2: return [p, v, t];
    case 3: return [p, q, v];
    case 4: return [t, p, v];
    default: return [v, p, q];
  }
}

/** Colour for a normalised scalar in 0..1. */
export function lookup(t: number): [number, number, number] {
  const clamped = t < 0 ? 0 : t > 1 ? 1 : t;
  return hsvToRgb(HUE_LOW + (HUE_HIGH - HUE_LOW) * clamped, 1, 1);
}

/**
 * Fill a flat rgb float buffer from scalars, normalised over [min, max].
 * Writes in place so switching the scalar field does not reallocate 60k
 * vertices worth of colour on every change.
 */
export function colorize(
  values: Float32Array,
  min: number,
  max: number,
  out: Float32Array,
): void {
  const span = max - min;
  const scale = span > 0 ? 1 / span : 0;
  for (let i = 0; i < values.length; i++) {
    const [r, g, b] = lookup((values[i] - min) * scale);
    out[i * 3] = r;
    out[i * 3 + 1] = g;
    out[i * 3 + 2] = b;
  }
}

/** A CSS gradient matching the ramp, for the legend strip. */
export function cssGradient(stops = 12): string {
  const parts: string[] = [];
  for (let i = 0; i < stops; i++) {
    const t = i / (stops - 1);
    const [r, g, b] = lookup(t);
    const c = `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
    parts.push(`${c} ${(t * 100).toFixed(1)}%`);
  }
  // Bottom is the low end, matching a vtkScalarBarActor drawn vertically.
  return `linear-gradient(to top, ${parts.join(", ")})`;
}
