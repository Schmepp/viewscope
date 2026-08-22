/** A titled, closable panel: the web equivalent of one QDockWidget. */

import type { ReactNode } from "react";

interface DockProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Lets a panel own its own scrolling, as the viewpoint table does. */
  flush?: boolean;
}

export function Dock({ title, onClose, children, flush }: DockProps) {
  return (
    <section className="dock">
      <header className="dock-title">
        <span>{title}</span>
        <button type="button" onClick={onClose} aria-label={`Close ${title}`}>
          ×
        </button>
      </header>
      <div className={flush ? "dock-body dock-body-flush" : "dock-body"}>{children}</div>
    </section>
  );
}

interface SplitterProps {
  side: "left" | "right";
  width: number;
  onResize: (value: number) => void;
}

/** Drag handle between a rail and the viewport. */
export function Splitter({ side, width, onResize }: SplitterProps) {
  return (
    <div
      className="splitter"
      role="separator"
      aria-orientation="vertical"
      onPointerDown={(event) => {
        const startX = event.clientX;
        const startWidth = width;
        const element = event.currentTarget;
        element.setPointerCapture(event.pointerId);

        const move = (e: PointerEvent) => {
          const delta = e.clientX - startX;
          onResize(side === "left" ? startWidth + delta : startWidth - delta);
        };
        const up = () => {
          element.releasePointerCapture(event.pointerId);
          element.removeEventListener("pointermove", move);
          element.removeEventListener("pointerup", up);
        };
        element.addEventListener("pointermove", move);
        element.addEventListener("pointerup", up);
      }}
    />
  );
}
