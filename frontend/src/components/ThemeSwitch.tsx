import { animated, to, useSpring } from "@react-spring/web";
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useReducedMotion } from "../hooks/useReducedMotion";
import type { Theme } from "../hooks/useTheme";
import { MoonStarIcon, SunIcon } from "./icons";
import { focusRing } from "./ui";

const segment = `relative z-10 grid size-8 place-items-center rounded-xl max-[720px]:size-11 ${focusRing}`;

// How far the thumb reaches into the other segment on hover, as a share of the switch's width.
const STRETCH = 14;

const OPTIONS: { value: Theme; label: string; Icon: typeof SunIcon }[] = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonStarIcon },
];

function Glyph({ on, calm, children }: { on: boolean; calm: boolean; children: ReactNode }) {
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
  const calm = useReducedMotion();
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
          left: to([thumb.pos, thumb.ext], (p, e) => `calc(2px + ${p} * (50% - 1px) - ${Math.max(-e, 0) * STRETCH}%)`),
          width: thumb.ext.to((e) => `calc(50% - 3px + ${Math.abs(e) * STRETCH}%)`),
          y: hop.v.to((v) => -4 * v),
          scale: hop.v.to((v) => 1 + 0.12 * v),
        }}
        className="absolute inset-y-0.5 rounded-xl bg-accent shadow-sm"
      />
      {OPTIONS.map(({ value, label, Icon }) => {
        const on = value === theme;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={on}
            aria-label={label}
            tabIndex={on ? 0 : -1}
            onClick={() => pick(value)}
            onPointerEnter={hover(value)}
            onPointerLeave={hover(null)}
            className={segment}
          >
            <Glyph on={on} calm={calm}>
              <Icon size={16} />
            </Glyph>
          </button>
        );
      })}
    </div>
  );
}
