import { DialogTitle } from "@headlessui/react";
import { useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { authErrorMessage, passwordHint } from "../lib/auth";
import { CheckIcon } from "./icons";
import { Button, Modal, PressButton, TextField } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ChangePasswordDialog({ open, onClose }: Props) {
  return (
    <Modal open={open} onClose={onClose} className="w-[min(92vw,26rem)]">
      <ChangePasswordForm onClose={onClose} />
    </Modal>
  );
}

// Mounts only while the dialog is open, so the passwords never outlive it.
function ChangePasswordForm({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  const nextHint = next ? passwordHint(next) : null;
  const mismatch = confirm !== "" && confirm !== next ? "The passwords do not match" : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    const hint = passwordHint(next);
    if (hint) {
      setError(`New password: ${hint.toLowerCase()}`);
      return nextRef.current?.focus();
    }
    if (confirm !== next) {
      setError("The passwords do not match");
      return confirmRef.current?.focus();
    }
    setPending(true);
    setError(null);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      setDone(true);
    } catch (err) {
      setError(authErrorMessage(err));
      const status = (err as { status?: number }).status;
      (status === 422 ? nextRef : currentRef).current?.focus();
    } finally {
      setPending(false);
    }
  }

  if (done) {
    return (
      <div className="flex flex-col gap-4 p-5">
        <DialogTitle as="h2" className="font-display text-lg font-semibold">
          Change password
        </DialogTitle>
        <p role="status" className="flex items-start gap-2">
          <CheckIcon className="mt-1 flex-none text-accent" />
          Password changed. Your other devices have been signed out.
        </p>
        <div className="flex justify-end">
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 p-5">
      <DialogTitle as="h2" className="font-display text-lg font-semibold">
        Change password
      </DialogTitle>
      <TextField
        ref={currentRef}
        label="Current password"
        name="current-password"
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <TextField
        ref={nextRef}
        label="New password"
        name="new-password"
        type="password"
        autoComplete="new-password"
        required
        value={next}
        onChange={(e) => setNext(e.target.value)}
        description="10-128 characters"
        error={nextHint}
      />
      <TextField
        ref={confirmRef}
        label="Confirm new password"
        name="confirm-password"
        type="password"
        autoComplete="new-password"
        required
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        error={mismatch}
      />
      <p role="alert" className="text-[13px] text-warn-bar empty:sr-only">
        {error}
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <PressButton type="submit" disabled={pending} hover={1.02} press={0.97} variant="primary">
          {pending ? "Saving…" : "Change password"}
        </PressButton>
      </div>
    </form>
  );
}
