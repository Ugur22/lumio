import { animated, useSpring } from "@react-spring/web";
import { useState, type ComponentPropsWithoutRef } from "react";

type Props = Omit<ComponentPropsWithoutRef<"button">, "style"> & {
  hover?: number;
  press?: number;
};

type Phase = "idle" | "hover" | "press";

// One spring-driven press feel for every button, so interactions are consistent.
export function PressButton({ hover = 1.05, press = 0.93, disabled, ...rest }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const { scale } = useSpring({
    scale: disabled ? 1 : phase === "press" ? press : phase === "hover" ? hover : 1,
    config: { tension: 520, friction: 22 },
  });

  return (
    <animated.button
      {...rest}
      disabled={disabled}
      style={{ scale }}
      onPointerEnter={() => setPhase("hover")}
      onPointerLeave={() => setPhase("idle")}
      onPointerDown={() => setPhase("press")}
      onPointerUp={() => setPhase("hover")}
      onPointerCancel={() => setPhase("idle")}
    />
  );
}
