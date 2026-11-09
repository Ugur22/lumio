import { useEffect, useRef, useState } from "react";
import { oauthStartUrl, type OAuthProvider } from "../lib/oauth";
import { TRIAL_PITCH } from "../lib/trial";
import { useInviteLink } from "../store/invite";
import { useSession } from "../store/session";
import { GitHubIcon, GoogleIcon } from "./icons";
import { TextField, cx, focusRing } from "./ui";

const oauthLink = cx(
  "flex min-h-11 items-center justify-center gap-2 rounded-xl border border-border bg-bg px-3 py-2 text-[14px] font-medium text-text transition-colors hover:border-accent/50 hover:bg-bubble",
  focusRing,
);

const PROVIDERS: { id: OAuthProvider; label: string; Icon: typeof GoogleIcon }[] = [
  { id: "google", label: "Continue with Google", Icon: GoogleIcon },
  { id: "github", label: "Continue with GitHub", Icon: GitHubIcon },
];

// Plain links: the server answers with a redirect to the provider, so the browser has to navigate, not fetch.
// Below the tabs, so one copy serves both the sign-in and the create-account view.
export function OAuthButtons() {
  const inviteHint = useSession((s) => s.inviteHint);
  const link = useInviteLink();
  // The code lives only in this field's state; it reaches the URL of the click and nowhere else.
  const [typed, setTyped] = useState("");
  // A code from the invite link wins, and its card already shows it, so the manual field steps aside.
  const fromLink = link.code !== null;
  const invite = link.code ?? typed;
  const [open, setOpen] = useState(inviteHint);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!inviteHint) return;
    setOpen(true);
    inputRef.current?.focus();
  }, [inviteHint]);

  // An account invite is for the registration form, which is open already; a trial one needs these buttons.
  if (link.phase === "applied" && link.kind === "account") return null;

  return (
    <section aria-label="Free trial" className="flex flex-col gap-3 border-t border-border pt-5">
      <div className="flex flex-col gap-2">
        {PROVIDERS.map(({ id, label, Icon }) => (
          <a key={id} href={oauthStartUrl(id, invite)} className={oauthLink}>
            <Icon className="flex-none" />
            <span>{label}</span>
          </a>
        ))}
      </div>
      {!fromLink && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls="trial-invite"
            onClick={() => setOpen((o) => !o)}
            className={cx("self-center rounded-md px-1 text-[13px] text-muted underline-offset-2 hover:text-text hover:underline", focusRing)}
          >
            Have an invite code?
          </button>
          <div id="trial-invite" hidden={!open}>
            <TextField
              ref={inputRef}
              label="Trial invite code"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              maxLength={256}
              surface
              value={invite}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
        </div>
      )}
      <p className="text-center text-[13px] text-muted">{TRIAL_PITCH}</p>
    </section>
  );
}
