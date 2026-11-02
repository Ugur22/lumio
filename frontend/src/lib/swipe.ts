// Width of the strip along the left edge where a rightward swipe opens the drawer.
export const EDGE = 24;
const MIN_DISTANCE = 56;
// Mostly horizontal only, so scrolling the chat list or message list never toggles the drawer.
const DOMINANCE = 1.5;

export interface Swipe {
  startX: number;
  dx: number;
  dy: number;
}

export function drawerSwipe(open: boolean, { startX, dx, dy }: Swipe): "open" | "close" | null {
  if (Math.abs(dx) < MIN_DISTANCE || Math.abs(dx) < Math.abs(dy) * DOMINANCE) return null;
  if (!open && dx > 0 && startX <= EDGE) return "open";
  if (open && dx < 0) return "close";
  return null;
}
