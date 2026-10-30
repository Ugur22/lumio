import { Button as HeadlessButton } from "@headlessui/react";
import type { ComponentPropsWithRef, ReactNode } from "react";
import { SpinnerIcon } from "../icons";
import { buttonVariants, cx, type ButtonVariant } from "./styles";

export type ButtonProps = Omit<ComponentPropsWithRef<"button">, "style"> & {
  variant?: ButtonVariant;
  // A pending action: shows a spinner and ignores clicks, but stays focusable and undimmed, unlike `disabled`.
  loading?: boolean;
};

export function ButtonContent({ loading, children }: { loading: boolean; children: ReactNode }) {
  if (!loading) return children;
  return (
    <span className="inline-flex items-center justify-center gap-2">
      <SpinnerIcon width={14} height={14} aria-hidden="true" className="shrink-0 motion-safe:animate-spin" />
      {children}
    </span>
  );
}

// The plain button: no press animation. Use PressButton where a button should spring.
export function Button({ variant = "ghost", loading = false, className, onClick, children, ...rest }: ButtonProps) {
  return (
    <HeadlessButton
      type="button"
      {...rest}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      onClick={loading ? undefined : onClick}
      className={cx(buttonVariants[variant], className)}
    >
      <ButtonContent loading={loading}>{children}</ButtonContent>
    </HeadlessButton>
  );
}
