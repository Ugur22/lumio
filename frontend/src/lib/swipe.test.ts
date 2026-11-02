import { describe, expect, it } from "vitest";
import { drawerSwipe } from "./swipe";

describe("drawerSwipe", () => {
  it("opens on a rightward swipe that starts at the left edge", () => {
    expect(drawerSwipe(false, { startX: 8, dx: 90, dy: 10 })).toBe("open");
  });

  it("ignores a rightward swipe that starts away from the edge", () => {
    expect(drawerSwipe(false, { startX: 120, dx: 90, dy: 0 })).toBeNull();
  });

  it("closes on a leftward swipe while open, from anywhere", () => {
    expect(drawerSwipe(true, { startX: 200, dx: -80, dy: 5 })).toBe("close");
  });

  it("does not close on a rightward swipe or open on a leftward one", () => {
    expect(drawerSwipe(true, { startX: 8, dx: 90, dy: 0 })).toBeNull();
    expect(drawerSwipe(false, { startX: 8, dx: -90, dy: 0 })).toBeNull();
  });

  it("ignores short or mostly vertical gestures", () => {
    expect(drawerSwipe(false, { startX: 8, dx: 30, dy: 0 })).toBeNull();
    expect(drawerSwipe(true, { startX: 200, dx: -80, dy: 70 })).toBeNull();
  });
});
