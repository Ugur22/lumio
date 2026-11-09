import { useEffect } from "react";
import { inviteReasonText } from "../lib/invites";
import { useInviteLink } from "../store/invite";
import { AlertIcon, CheckIcon, CloseIcon } from "./icons";
import { cx, focusRing } from "./ui";

const box = "flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-[13px]";

// Reads the invite from the address bar on first mount (once per page load, see the store) and says what became of it.
export function InviteCard() {
  const { phase, kind, reason, problem } = useInviteLink();

  useEffect(() => {
    useInviteLink.getState().start();
  }, []);

  if (phase === "none") return null;

  if (phase === "invalid") {
    return (
      <div role="alert" className={cx(box, "border-warn-bar bg-warn-bg text-warn-bar")}>
        <AlertIcon width={16} height={16} className="mt-0.5 flex-none" />
        <p className="flex-1">{inviteReasonText(reason)}</p>
      </div>
    );
  }

  if (phase === "checking") {
    return (
      <p role="status" className={cx(box, "border-border bg-bg text-muted")}>
        Checking your invite…
      </p>
    );
  }

  const applied = phase === "applied";
  return (
    <div role="status" className={cx(box, "border-accent/50 bg-bubble")}>
      <CheckIcon width={16} height={16} className="mt-0.5 flex-none text-accent" />
      <div className="min-w-0 flex-1">
        {applied ? (
          <>
            <p className="font-semibold">Invite applied</p>
            <p className="text-muted">{kind === "account" ? "Create your account" : "Sign in to start free"}</p>
          </>
        ) : (
          <>
            <p className="font-semibold">Invite added</p>
            <p className="text-muted">{problem}</p>
          </>
        )}
      </div>
      <button
        type="button"
        aria-label="Remove invite"
        onClick={() => useInviteLink.getState().remove()}
        className={cx("grid size-7 flex-none place-items-center rounded-md text-muted hover:text-text", focusRing)}
      >
        <CloseIcon width={16} height={16} />
      </button>
    </div>
  );
}
