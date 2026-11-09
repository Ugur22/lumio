import { animated, useSpring } from "@react-spring/web";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import type { Theme } from "../hooks/useTheme";
import { MoonStarIcon, SunIcon } from "./icons";
import { focusRing } from "./ui";

const segment = `relative z-10 grid size-8 place-items-center rounded-full max-[720px]:size-11 ${focusRing}`;

function Glyph({ on, children }: { on: boolean; children: ReactNode }) {
  const calm = useMediaQuery("(prefers-reduced-motion: reduce)");
  const style = useSpring({
    rotate: on ? 0 : -50,
    scale: on ? 1 : 0.8,
    immediate: calm,
    config: { tension: 380, friction: 18 },
  });
  return (
    <animated.span style={style} className={`grid place-items-center transition-colors duration-200 ${on ? "text-on-accent" : "text-muted"}`}>
      {children}
    </animated.span>
  );
}

// Shows the current theme and lets either side be picked, instead of one button naming the action.
export function ThemeSwitch({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const calm = useMediaQuery("(prefers-reduced-motion: reduce)");
  const dark = theme === "dark";
  // Low friction so the thumb overshoots and settles; `hop` rises and lands with it, so the move reads as a jump.
  const thumb = useSpring({ x: dark ? 100 : 0, immediate: calm, config: { tension: 320, friction: 15 } });
  const [hop, hopApi] = useSpring(() => ({ v: 0 }));
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (!calm) hopApi.start({ from: { v: 1 }, to: { v: 0 }, config: { tension: 260, friction: 9 } });
  }, [dark, calm, hopApi]);

  const pick = (next: Theme) => {
    if (next !== theme) onToggle();
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") pick("light");
    else if (e.key === "ArrowRight" || e.key === "ArrowDown") pick("dark");
    else return;
    e.preventDefault();
  };

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      onKeyDown={onKeyDown}
      className="relative grid flex-none grid-cols-2 gap-0.5 rounded-2xl border border-border bg-bubble p-0.5"
    >
      <animated.span
        aria-hidden="true"
        style={{
          transform: thumb.x.to((x) => `translateX(calc(${x}% + ${x / 50}px))`),
          y: hop.v.to((v) => -4 * v),
          scale: hop.v.to((v) => 1 + 0.12 * v),
        }}
        className="absolute inset-y-0.5 left-0.5 w-[calc(50%-3px)] rounded-xl bg-accent shadow-sm"
      />
      <button type="button" role="radio" aria-checked={!dark} aria-label="Light" tabIndex={dark ? -1 : 0} onClick={() => pick("light")} className={segment}>
        <Glyph on={!dark}>
          <SunIcon size={16} />
        </Glyph>
      </button>
      <button type="button" role="radio" aria-checked={dark} aria-label="Dark" tabIndex={dark ? 0 : -1} onClick={() => pick("dark")} className={segment}>
        <Glyph on={dark}>
          <MoonStarIcon size={16} />
        </Glyph>
      </button>
    </div>
  );
}
