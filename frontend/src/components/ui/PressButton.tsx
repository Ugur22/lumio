import { Button } from "@headlessui/react";
import { animated, useSpring } from "@react-spring/web";
import { useState, useSyncExternalStore } from "react";
import { ButtonContent, type ButtonProps } from "./Button";
import { buttonVariants, cx } from "./styles";

type Props = ButtonProps & {
  hover?: number;
  press?: number;
};

type Phase = "idle" | "hover" | "press";

const TOUCH = "(hover: none), (pointer: coarse)";

// Not useMediaQuery: unit tests render buttons without a matchMedia stub.
function subscribe(onChange: () => void) {
  if (typeof matchMedia !== "function") return () => undefined;
  const media = matchMedia(TOUCH);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const isTouch = () => typeof matchMedia === "function" && matchMedia(TOUCH).matches;

// Desktop gets the spring feel; touch screens get a CSS :active scale, which runs off the main thread
// and avoids the sticky hover state a tap would leave behind.
export function PressButton(props: Props) {
  const touch = useSyncExternalStore(subscribe, isTouch, () => false);
  return touch ? <TouchPressButton {...props} /> : <SpringPressButton {...props} />;
}

function TouchPressButton({ hover, press, variant, loading = false, disabled, className, onClick, children, ...rest }: Props) {
  // Only the spring variant scales by these; they must not reach the DOM through rest.
  void hover;
  void press;
  return (
    <Button
      {...rest}
      disabled={disabled}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      onClick={loading ? undefined : onClick}
      className={cx(
        variant && buttonVariants[variant],
        "transition-transform duration-100 ease-out active:scale-[0.97] disabled:active:scale-100 motion-reduce:transition-none",
        className,
      )}
    >
      <ButtonContent loading={loading}>{children}</ButtonContent>
    </Button>
  );
}

// One spring-driven press feel for every button, so interactions are consistent.
function SpringPressButton({ hover = 1.05, press = 0.93, variant, loading = false, disabled, className, onClick, children, ...rest }: Props) {
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
