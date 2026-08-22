/**
 * Port of ViewpointPanel: one row per planned camera, selecting a row jumps
 * the viewport. Keeps the QTableWidget behaviour of scrolling the selection
 * into view when the choice was made elsewhere (Next / Previous / number
 * keys), which is what select_row did with _suppress guarding re-entry.
 */

import { useEffect, useRef } from "react";
import type { Viewpoint } from "../data/bundle";

interface ViewpointPanelProps {
  viewpoints: Viewpoint[];
  selected: number | null;
  onSelect: (index: number) => void;
}

export function ViewpointPanel({ viewpoints, selected, onSelect }: ViewpointPanelProps) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selected === null || !bodyRef.current) return;
    bodyRef.current
      .querySelector(`[data-row="${selected}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  return (
    <div className="table-wrap" ref={bodyRef}>
      <table className="viewpoints">
        <thead>
          <tr>
            <th>#</th>
            <th>Position</th>
            <th>Yaw</th>
            <th>Pitch</th>
          </tr>
        </thead>
        <tbody>
          {viewpoints.map((vp, i) => (
            <tr
              key={vp.id}
              data-row={i}
              className={i === selected ? "selected" : undefined}
              onClick={() => onSelect(i)}
            >
              <td>{i + 1}</td>
              <td>
                {vp.position[0].toFixed(1)}, {vp.position[1].toFixed(1)},{" "}
                {vp.position[2].toFixed(1)}
              </td>
              <td>{vp.yaw_deg.toFixed(1)}</td>
              <td>{vp.pitch_deg.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
