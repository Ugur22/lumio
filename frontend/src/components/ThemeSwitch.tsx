import { animated, to, useSpring } from "@react-spring/web";
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
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
  // Hovering the other side stretches the thumb over part of it (it stays fully on its own side), as a hint of where a
  // click will take it. `ext` is signed: positive grows it to the right, negative to the left.
  const [hovered, setHovered] = useState<Theme | null>(null);
  const toward = hovered !== null && hovered !== theme ? (dark ? -1 : 1) : 0;
  // Low friction so the thumb overshoots and settles; `hop` rises and lands with it, so the move reads as a jump.
  const thumb = useSpring({ pos: dark ? 1 : 0, ext: toward, immediate: calm, config: { tension: 320, friction: 15 } });
  const [hop, hopApi] = useSpring(() => ({ v: 0 }));
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (!calm) hopApi.start({ from: { v: 1 }, to: { v: 0 }, config: { tension: 260, friction: 9 } });
  }, [dark, calm, hopApi]);

  // Touch has no hover; the pointer events of a tap would otherwise leave the thumb leaning.
  const hover = (next: Theme | null) => (e: PointerEvent) => {
    if (e.pointerType === "mouse") setHovered(next);
  };
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
          left: to([thumb.pos, thumb.ext], (p, e) => `calc(2px + ${p} * (50% - 1px) - ${Math.max(-e, 0) * 14}%)`),
          width: thumb.ext.to((e) => `calc(50% - 3px + ${Math.abs(e) * 14}%)`),
          y: hop.v.to((v) => -4 * v),
          scale: hop.v.to((v) => 1 + 0.12 * v),
        }}
        className="absolute inset-y-0.5 rounded-xl bg-accent shadow-sm"
      />
      <button type="button" role="radio" aria-checked={!dark} aria-label="Light" tabIndex={dark ? -1 : 0} onClick={() => pick("light")} onPointerEnter={hover("light")} onPointerLeave={hover(null)} className={segment}>
        <Glyph on={!dark}>
          <SunIcon size={16} />
        </Glyph>
      </button>
      <button type="button" role="radio" aria-checked={dark} aria-label="Dark" tabIndex={dark ? 0 : -1} onClick={() => pick("dark")} onPointerEnter={hover("dark")} onPointerLeave={hover(null)} className={segment}>
        <Glyph on={dark}>
          <MoonStarIcon size={16} />
        </Glyph>
      </button>
    </div>
  );
}
