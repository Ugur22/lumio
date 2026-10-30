import { Description, DialogTitle } from "@headlessui/react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { PressButton } from "./PressButton";

interface Props {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel: string;
  // A destructive action gets the warning style instead of the accent.
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

// Replaces window.confirm. Focus starts on Cancel, so Enter never confirms by accident.
export function ConfirmDialog({ open, title, description, confirmLabel, danger, onConfirm, onCancel }: Props) {
  return (
    <Modal open={open} onClose={onCancel} className="w-[min(92vw,24rem)]">
      <div className="flex flex-col gap-4 p-5">
        <DialogTitle as="h2" className="font-display text-lg font-semibold">
          {title}
        </DialogTitle>
        {description && <Description className="text-muted">{description}</Description>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <PressButton onClick={onConfirm} hover={1.02} press={0.97} variant={danger ? "destructive" : "primary"}>
            {confirmLabel}
          </PressButton>
        </div>
      </div>
    </Modal>
  );
}
