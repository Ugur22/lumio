import { Dialog, DialogBackdrop, DialogPanel, DialogTitle } from "@headlessui/react";
import type { ReactNode } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

// Phone counterpart of Modal: same Headless Dialog (focus trap, scroll lock, Escape, scrim tap), anchored to the bottom.
export function BottomSheet({ open, onClose, title, children }: Props) {
  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <DialogBackdrop
        transition
        className="fixed inset-0 bg-black/40 transition-opacity duration-200 data-[closed]:opacity-0 motion-reduce:transition-none"
      />
      <div className="fixed inset-x-0 bottom-0 flex justify-center">
        <DialogPanel
          transition
          className="max-h-[85dvh] w-full max-w-[560px] overflow-y-auto overscroll-contain rounded-t-2xl border border-b-0 border-border bg-surface px-4 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] pt-2 text-text shadow-lift transition-transform duration-200 ease-out data-[closed]:translate-y-full motion-reduce:transition-none"
        >
          <div aria-hidden="true" className="mx-auto mb-3 h-1 w-10 rounded-full bg-border" />
          <DialogTitle className="mb-2 text-[15px] font-semibold">{title}</DialogTitle>
          {children}
        </DialogPanel>
      </div>
    </Dialog>
  );
}
