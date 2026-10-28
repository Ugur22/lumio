import { animated, to, useSpring } from "@react-spring/web";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { CloseIcon } from "./icons";

export interface Origin {
  thumb: DOMRect;
  // The scroll area the thumbnail lives in; the flight is clipped to it so it never draws over the header.
  bounds: DOMRect | null;
}

interface Props {
  src: string;
  alt: string;
  // Read at open and close time, so the image lands on the thumbnail even if the chat scrolled.
  getOrigin: () => Origin | null;
  onClose: () => void;
}

const NO_CLIP = { clipT: 0, clipR: 0, clipB: 0, clipL: 0 };

// Distances from each viewport edge to the visible area, as the spring's clip insets.
function clipFor(bounds: Origin["bounds"]) {
  if (!bounds) return NO_CLIP;
  return {
    clipT: Math.max(0, bounds.top),
    clipR: Math.max(0, window.innerWidth - bounds.right),
    clipB: Math.max(0, window.innerHeight - bounds.bottom),
    clipL: Math.max(0, bounds.left),
  };
}

// Where the thumbnail sits relative to the centred image, as the spring's starting transform.
function fromOrigin(origin: Origin | null, target: DOMRect) {
  if (!origin) return { x: 0, y: 0, scale: 0.96, ...NO_CLIP };
  const { thumb: o } = origin;
  return {
    ...clipFor(origin.bounds),
    x: o.left + o.width / 2 - (target.left + target.width / 2),
    y: o.top + o.height / 2 - (target.top + target.height / 2),
    scale: o.width / target.width,
  };
}

export function ImageLightbox({ src, alt, getOrigin, onClose }: Props) {
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const img = useRef<HTMLImageElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  // The resting rect, captured once: reading it mid-animation would include the transform.
  const target = useRef<DOMRect | null>(null);
  const closing = useRef(false);
  const [style, api] = useSpring(() => ({ x: 0, y: 0, scale: 1, fade: 0, scrim: 0, ...NO_CLIP }));

  useEffect(() => {
    closeButton.current?.focus();
    api.start({ scrim: 1, immediate: reduceMotion, config: { tension: 300, friction: 30 } });
  }, [api, reduceMotion]);

  function onLoad() {
    const el = img.current;
    if (!el) return;
    target.current = el.getBoundingClientRect();
    // `from` jumps to the thumbnail instantly; the image is invisible until now, so nothing flashes.
    api.start({
      from: { ...fromOrigin(getOrigin(), target.current), fade: 1 },
      to: { x: 0, y: 0, scale: 1, fade: 1, ...NO_CLIP },
      immediate: reduceMotion,
      config: { tension: 320, friction: 30 },
    });
  }

  function close() {
    if (closing.current) return;
    closing.current = true;
    if (reduceMotion || !target.current) {
      onClose();
      return;
    }
    api.start({
      ...fromOrigin(getOrigin(), target.current),
      scrim: 0,
      config: { tension: 380, friction: 34 },
      onRest: (result) => {
        if (result.finished) onClose();
      },
    });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      // The close button is the only control, so Tab stays on it rather than leaking behind the scrim.
      if (e.key === "Tab") {
        e.preventDefault();
        closeButton.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={alt} className="fixed inset-0 z-50 grid place-items-center p-4">
      <animated.div
        aria-hidden="true"
        style={{ opacity: style.scrim }}
        onClick={close}
        className="absolute inset-0 bg-black/75"
      />
      {/* Not transformed itself, so its clip stays in viewport coordinates while the image inside moves. */}
      <animated.div
        style={{
          clipPath: to(
            [style.clipT, style.clipR, style.clipB, style.clipL],
            (t, r, b, l) => `inset(${t}px ${r}px ${b}px ${l}px)`,
          ),
        }}
        className="pointer-events-none absolute inset-0 grid place-items-center p-4"
      >
        <animated.img
          ref={img}
          src={src}
          alt={alt}
          onLoad={onLoad}
          onClick={close}
          style={{ x: style.x, y: style.y, scale: style.scale, opacity: style.fade }}
          className="pointer-events-auto max-h-[88dvh] max-w-[min(92vw,1400px)] cursor-zoom-out rounded-xl object-contain shadow-lift"
        />
      </animated.div>
      <animated.button
        ref={closeButton}
        type="button"
        aria-label="Close image"
        onClick={close}
        style={{ opacity: style.scrim }}
        className="absolute right-[max(1rem,env(safe-area-inset-right,0px))] top-[max(1rem,env(safe-area-inset-top,0px))] grid size-10 place-items-center rounded-full bg-black/50 text-white backdrop-blur hover:bg-black/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      >
        <CloseIcon />
      </animated.button>
    </div>,
    document.body,
  );
}
