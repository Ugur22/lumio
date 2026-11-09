import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from "@headlessui/react";
import { animated, useTransition } from "@react-spring/web";
import type { ReactNode } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  // Renders the title as a small uppercase section label (for titles that are fixed UI text, not user content).
  eyebrow?: boolean;
  children: ReactNode;
}

// Phone counterpart of Modal: same Headless Dialog (focus trap, scroll lock, Escape, scrim tap), anchored to the bottom.
export function BottomSheet({ open, onClose, title, eyebrow = false, children }: Props) {
  const calm = useReducedMotion();
  const transition = useTransition(open, {
    from: { o: 0, y: 100 },
    enter: { o: 1, y: 0 },
    leave: { o: 0, y: 100 },
    immediate: calm,
    config: (_item, _index, phase) => (phase === "leave" ? { tension: 380, friction: 34 } : { tension: 300, friction: 26 }),
  });

  return transition(
    (style, show) =>
      show && (
        <Dialog static open onClose={onClose} className="relative z-50">
          <DialogBackdrop as={animated.div} style={{ opacity: style.o }} className="fixed inset-0 bg-black/40" />
          <div className="fixed inset-x-0 bottom-0 flex justify-center">
            <DialogPanel
              as={animated.div}
              style={{ transform: style.y.to((y) => `translateY(${y}%)`) }}
              className="max-h-[85dvh] w-full max-w-[560px] overflow-y-auto overscroll-contain rounded-t-3xl border border-b-0 border-border bg-surface px-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] pt-2 text-text shadow-lift"
            >
              <div aria-hidden="true" className="mx-auto mb-2.5 h-[5px] w-9 rounded-full bg-border" />
              <DialogTitle className={eyebrow ? "mb-1 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted" : "mb-2 text-[15px] font-semibold"}>{title}</DialogTitle>
              {children}
            </DialogPanel>
          </div>
        </Dialog>
      ),
  );
}
