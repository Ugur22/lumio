import { DialogTitle } from "@headlessui/react";
import { useState, type FormEvent } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { PressButton } from "./PressButton";
import { TextField } from "./TextField";

interface Props {
  open: boolean;
  title: string;
  label: string;
  initialValue: string;
  submitLabel: string;
  maxLength?: number;
  // Only called with a non-blank, trimmed value.
  onSubmit: (value: string) => void;
  onCancel: () => void;
}

// Replaces window.prompt. The form mounts only while open, so each use starts from `initialValue`.
export function PromptDialog({ open, onCancel, ...form }: Props) {
  return (
    <Modal open={open} onClose={onCancel} className="w-[min(92vw,26rem)]">
      <PromptForm {...form} onCancel={onCancel} />
    </Modal>
  );
}

function PromptForm({ title, label, initialValue, submitLabel, maxLength, onSubmit, onCancel }: Omit<Props, "open">) {
  const [value, setValue] = useState(initialValue);
  const trimmed = value.trim();

  function submit(e: FormEvent) {
    e.preventDefault();
    if (trimmed) onSubmit(trimmed);
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 p-5">
      <DialogTitle as="h2" className="font-display text-lg font-semibold">
        {title}
      </DialogTitle>
      <TextField
        label={label}
        value={value}
        maxLength={maxLength}
        onChange={(e) => setValue(e.target.value)}
        onFocus={(e) => e.currentTarget.select()}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button onClick={onCancel}>Cancel</Button>
        <PressButton type="submit" disabled={!trimmed} hover={1.02} press={0.97} variant="primary">
          {submitLabel}
        </PressButton>
      </div>
    </form>
  );
}
