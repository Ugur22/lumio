import { useEffect } from "react";
import { drawerSwipe } from "../lib/swipe";

// Document-level, because the opening swipe starts on whatever sits under the left edge, not on the drawer.
export function useDrawerSwipe(enabled: boolean, open: boolean, onOpenChange: (open: boolean) => void) {
  useEffect(() => {
    if (!enabled) return;
    let start: { x: number; y: number } | null = null;
    const down = (e: TouchEvent) => {
      const t = e.touches.length === 1 ? e.touches[0] : undefined;
      start = t ? { x: t.clientX, y: t.clientY } : null;
    };
    const up = (e: TouchEvent) => {
      const t = e.changedTouches[0];
      if (!start || !t) return;
      const intent = drawerSwipe(open, { startX: start.x, dx: t.clientX - start.x, dy: t.clientY - start.y });
      start = null;
      if (intent) onOpenChange(intent === "open");
    };
    const cancel = () => {
      start = null;
    };
    document.addEventListener("touchstart", down, { passive: true });
    document.addEventListener("touchend", up, { passive: true });
    document.addEventListener("touchcancel", cancel, { passive: true });
    return () => {
      document.removeEventListener("touchstart", down);
      document.removeEventListener("touchend", up);
      document.removeEventListener("touchcancel", cancel);
    };
  }, [enabled, open, onOpenChange]);
}
