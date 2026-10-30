import { Dialog, DialogBackdrop, DialogPanel } from "@headlessui/react";
import type { ReactNode } from "react";
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
export function Modal({ open, onClose, className, children }: Props) {
  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <DialogBackdrop className="fixed inset-0 bg-black/40" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className={cx("max-h-full overflow-y-auto rounded-2xl border border-border bg-surface text-text shadow-lift", className)}>
          {children}
        </DialogPanel>
      </div>
    </Dialog>
  );
}
