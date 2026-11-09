import { Dialog, DialogBackdrop, DialogPanel } from "@headlessui/react";
import { animated, to, useTransition } from "@react-spring/web";
import type { ReactNode } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import { cx } from "./styles";

interface Props {
  open: boolean;
  // Called for Escape and for a click that starts and ends outside the panel. A parent that wants to keep the
  // dialog open (unsaved changes) simply leaves `open` true.
  onClose: () => void;
  // Sets the panel's width, e.g. "w-[min(92vw,30rem)]".
  className?: string;
  children: ReactNode;
}

// Headless Dialog supplies the focus trap, scroll lock, Escape and aria-labelledby (from a DialogTitle inside).
// `static` keeps it mounted while the spring plays the leave animation; the transition decides when it unmounts.
export function Modal({ open, onClose, className, children }: Props) {
  const calm = useReducedMotion();
  const transition = useTransition(open, {
    from: { o: 0, s: 0.94, y: 14 },
    enter: { o: 1, s: 1, y: 0 },
    leave: { o: 0, s: 0.97, y: 6 },
    immediate: calm,
    // A little overshoot on the way in, a firm settle on the way out.
    config: (_item, _index, phase) => (phase === "leave" ? { tension: 380, friction: 32 } : { tension: 300, friction: 19 }),
  });

  return transition(
    (style, show) =>
      show && (
        <Dialog static open onClose={onClose} className="relative z-50">
          <DialogBackdrop as={animated.div} style={{ opacity: style.o }} className="fixed inset-0 bg-black/40" />
          <div className="fixed inset-0 flex items-center justify-center p-4">
            <DialogPanel
              as={animated.div}
              style={{ opacity: style.o, transform: to([style.y, style.s], (y, s) => `translateY(${y}px) scale(${s})`) }}
              className={cx("max-h-full overflow-y-auto rounded-2xl border border-border bg-surface text-text shadow-lift", className)}
            >
              {children}
            </DialogPanel>
          </div>
        </Dialog>
      ),
  );
}
