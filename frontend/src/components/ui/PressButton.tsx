import { Button } from "@headlessui/react";
import { animated, useSpring } from "@react-spring/web";
import { useState } from "react";
import { ButtonContent, type ButtonProps } from "./Button";
import { buttonVariants, cx } from "./styles";

type Props = ButtonProps & {
  hover?: number;
  press?: number;
};

type Phase = "idle" | "hover" | "press";

// One spring-driven press feel for every button, so interactions are consistent.
export function PressButton({ hover = 1.05, press = 0.93, variant, loading = false, disabled, className, onClick, children, ...rest }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const inert = disabled || loading;
  const { scale } = useSpring({
    scale: inert ? 1 : phase === "press" ? press : phase === "hover" ? hover : 1,
    config: { tension: 520, friction: 22 },
  });

  return (
    <Button
      {...rest}
      as={animated.button}
      disabled={disabled}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      onClick={loading ? undefined : onClick}
      className={cx(variant && buttonVariants[variant], className)}
      style={{ scale }}
      onPointerEnter={() => setPhase("hover")}
      onPointerLeave={() => setPhase("idle")}
      onPointerDown={() => setPhase("press")}
      onPointerUp={() => setPhase("hover")}
      onPointerCancel={() => setPhase("idle")}
    >
      <ButtonContent loading={loading}>{children}</ButtonContent>
    </Button>
  );
}
