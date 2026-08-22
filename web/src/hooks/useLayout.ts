/**
 * Panel arrangement that survives a reload.
 *
 * The desktop stores QMainWindow.saveState() in QSettings and restores it in
 * the constructor. Browsers have no QSettings, so the same idea lands in
 * localStorage: which docks are open and how wide the two rails are.
 */

import { useCallback, useEffect, useState } from "react";

const KEY = "viewscope.layout.v1";

export type PanelId = "viewpoints" | "display" | "metrics";

export interface Layout {
  visible: Record<PanelId, boolean>;
  leftWidth: number;
  rightWidth: number;
}

export const DEFAULT_LAYOUT: Layout = {
  visible: { viewpoints: true, display: true, metrics: true },
  leftWidth: 300,
  rightWidth: 300,
};

function read(): Layout {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<Layout>;
    return {
      visible: { ...DEFAULT_LAYOUT.visible, ...(parsed.visible ?? {}) },
      leftWidth: parsed.leftWidth ?? DEFAULT_LAYOUT.leftWidth,
      rightWidth: parsed.rightWidth ?? DEFAULT_LAYOUT.rightWidth,
    };
  } catch {
    // A corrupt or blocked store is not worth failing the app over.
    return DEFAULT_LAYOUT;
  }
}

export function useLayout() {
  const [layout, setLayout] = useState<Layout>(read);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(layout));
    } catch {
      /* private mode, quota, whatever: the app still works without it */
    }
  }, [layout]);

  const togglePanel = useCallback((id: PanelId) => {
    setLayout((current) => ({
      ...current,
      visible: { ...current.visible, [id]: !current.visible[id] },
    }));
  }, []);

  const setWidth = useCallback((side: "leftWidth" | "rightWidth", value: number) => {
    setLayout((current) => ({
      ...current,
      [side]: Math.max(200, Math.min(560, value)),
    }));
  }, []);

  const reset = useCallback(() => setLayout(DEFAULT_LAYOUT), []);

  return { layout, togglePanel, setWidth, reset };
}
