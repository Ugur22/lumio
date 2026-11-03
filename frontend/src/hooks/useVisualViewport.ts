import { useEffect, useState } from "react";

// Below this the visual viewport only moved because of browser chrome (URL bar), not an on-screen keyboard.
const MIN_KEYBOARD = 80;

interface ViewportBox {
  height: number;
  offsetTop: number;
  scale: number;
}

// How much of the layout viewport the keyboard covers. Pinch-zoom also shrinks the visual viewport, so a zoomed page counts as none.
export function keyboardInset(layoutHeight: number, vv: ViewportBox): number {
  if (Math.abs(vv.scale - 1) > 0.01) return 0;
  const covered = Math.round(layoutHeight - vv.height - vv.offsetTop);
  return covered >= MIN_KEYBOARD ? covered : 0;
}

// iOS and Android Chrome leave the layout viewport alone when the keyboard opens, so a bottom-docked composer
// ends up underneath it. The inset is published as --kb-inset on <html> for the app root to subtract from its height.
export function useVisualViewport(): number {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const root = document.documentElement;
    let applied = "";
    let frame = 0;
    const update = () => {
      frame = 0;
      const next = keyboardInset(window.innerHeight, vv);
      // The keyboard animation fires many events; only a changed frame is worth style writes and a render.
      const key = `${next}|${vv.height}|${vv.offsetTop}|${vv.scale}`;
      if (key !== applied) {
        applied = key;
        root.style.setProperty("--kb-inset", `${next}px`);
        // The app root is pinned to the visual viewport, so iOS panning the page to reveal the field cannot push the header off-screen.
        if (Math.abs(vv.scale - 1) <= 0.01) {
          root.style.setProperty("--vv-height", `${vv.height}px`);
          root.style.setProperty("--vv-top", `${vv.offsetTop}px`);
        } else {
          root.style.removeProperty("--vv-height");
          root.style.removeProperty("--vv-top");
        }
        if (next > 0) root.dataset.keyboard = "open";
        else delete root.dataset.keyboard;
        setInset(next);
      }
      // iOS pans the page up to reveal the focused field; with the root already shrunk that pan only hides the header.
      if (next > 0 && window.scrollY !== 0) window.scrollTo(0, 0);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    vv.addEventListener("resize", schedule);
    vv.addEventListener("scroll", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      vv.removeEventListener("resize", schedule);
      vv.removeEventListener("scroll", schedule);
      for (const v of ["--kb-inset", "--vv-height", "--vv-top"]) root.style.removeProperty(v);
      delete root.dataset.keyboard;
    };
  }, []);

  return inset;
}
