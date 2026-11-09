import { Tab, TabGroup, TabList, TabPanel, TabPanels } from "@headlessui/react";
import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { api } from "../api";
import { authErrorMessage, normalizeUsername, passwordHint, usernameHint } from "../lib/auth";
import { useSession } from "../store/session";
import { useInviteLink } from "../store/invite";
import { LumioMark } from "./icons";
import { InviteCard } from "./InviteCard";
import { OAuthButtons } from "./OAuthButtons";
import { APP_NAME } from "../lib/brand";
import { PressButton, TextField, cx, focusRing } from "./ui";

const tabClass = (selected: boolean) =>
  cx(
    "flex-1 rounded-lg px-3 py-1.5 text-[14px] font-medium transition-colors",
    selected ? "bg-surface text-text shadow-soft" : "text-muted hover:text-text",
    focusRing,
  );

export function AuthScreen() {
  const notice = useSession((s) => s.notice);
  // Focus follows a tab switch, but not the first paint, so the page does not open with a field grabbed.
  const [switched, setSwitched] = useState(false);
  const [tab, setTab] = useState(0);
  // An account invite opens the registration form; the person can still switch back.
  const accountInvite = useInviteLink((s) => s.phase === "applied" && s.kind === "account");
  useEffect(() => {
    if (accountInvite) setTab(1);
  }, [accountInvite]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg p-4 font-sans text-[15px] leading-[1.6] text-text">
      <div className="flex w-full max-w-sm flex-col gap-5 rounded-2xl border border-border bg-surface p-6 shadow-lift max-[480px]:p-5">
        <div className="flex items-center gap-2.5">
          <LumioMark size={30} />
          <h1 className="font-display text-lg font-semibold">{APP_NAME}</h1>
        </div>
        {notice && (
          <p role="status" className="rounded-lg bg-note-bg px-3 py-2 text-[13px]">
            {notice}
          </p>
        )}
        <InviteCard />
        <TabGroup
          manual
          selectedIndex={tab}
          onChange={(i) => {
            setSwitched(true);
            setTab(i);
          }}
        >
          <TabList className="mb-5 flex gap-1 rounded-xl bg-bubble p-1">
            <Tab className={({ selected }) => tabClass(selected)}>Sign in</Tab>
            <Tab className={({ selected }) => tabClass(selected)}>Create account</Tab>
          </TabList>
          <TabPanels>
            <TabPanel unmount>
              <SignInForm focusOnMount={switched} />
            </TabPanel>
            <TabPanel unmount>
              <RegisterForm focusOnMount={switched} />
            </TabPanel>
          </TabPanels>
        </TabGroup>
        <OAuthButtons />
      </div>
    </main>
  );
}

type Field = "username" | "password" | "invite";

// Which field to put the cursor in after the server refused, so the fix is one keystroke away.
function fieldFor(status: number | undefined, fallback: Field): Field {
  if (status === 401) return "password";
  if (status === 403) return "invite";
  if (status === 409) return "username";
  return fallback;
}

function useFormRefs() {
  const refs: Record<Field, RefObject<HTMLInputElement | null>> = {
    username: useRef<HTMLInputElement>(null),
    password: useRef<HTMLInputElement>(null),
    invite: useRef<HTMLInputElement>(null),
  };
  return refs;
}

function ErrorText({ error }: { error: string | null }) {
  // Always rendered, so the live region exists before its text changes and the change is announced.
  return (
    <p role="alert" className="text-[13px] text-warn-bar empty:sr-only">
      {error}
    </p>
  );
}

function SubmitButton({ pending, children }: { pending: boolean; children: string }) {
  return (
    <PressButton type="submit" disabled={pending} hover={1.02} press={0.97} variant="primary">
      {pending ? "Please wait…" : children}
    </PressButton>
  );
}

function SignInForm({ focusOnMount }: { focusOnMount: boolean }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const refs = useFormRefs();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const user = await api.login({ username: normalizeUsername(username), password });
      setPassword("");
      useSession.getState().signIn(user);
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
      refs[fieldFor((err as { status?: number }).status, "username")].current?.focus();
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <TextField
        ref={refs.username}
        autoFocus={focusOnMount}
        label="Username"
        name="username"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        required
        surface
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <TextField
        ref={refs.password}
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        surface
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <ErrorText error={error} />
      <SubmitButton pending={pending}>Sign in</SubmitButton>
    </form>
  );
}

function RegisterForm({ focusOnMount }: { focusOnMount: boolean }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const linked = useInviteLink((s) => s.code);
  const [invite, setInvite] = useState(linked ?? "");
  // Removing the invite from the card empties the field it filled.
  useEffect(() => setInvite(linked ?? ""), [linked]);
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const refs = useFormRefs();

  const touch = (f: Field) => setTouched((t) => ({ ...t, [f]: true }));
  const nameHint = usernameHint(username);
  const pwHint = passwordHint(password);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const user = await api.register({ username: normalizeUsername(username), password, invite: invite.trim() });
      setPassword("");
      setInvite("");
      useSession.getState().signIn(user);
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
      const status = (err as { status?: number }).status;
      // A 422 does not say which field, so the first one the hints fault gets the cursor.
      const invalid: Field = nameHint ? "username" : pwHint ? "password" : "invite";
      refs[fieldFor(status, status === 422 ? invalid : "invite")].current?.focus();
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <TextField
        ref={refs.invite}
        autoFocus={focusOnMount}
        label="Invite code"
        name="invite"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        required
        surface
        value={invite}
        onChange={(e) => setInvite(e.target.value)}
      />
      <TextField
        ref={refs.username}
        label="Username"
        name="username"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        required
        surface
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        onBlur={() => touch("username")}
        description="3-32 characters: letters, digits, _ or -"
        error={touched.username && nameHint}
      />
      <TextField
        ref={refs.password}
        label="Password"
        name="new-password"
        type="password"
        autoComplete="new-password"
        required
        surface
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        onBlur={() => touch("password")}
        description={linked ? "At least 10 characters" : "10-128 characters"}
        error={touched.password && pwHint}
      />
      <ErrorText error={error} />
      <SubmitButton pending={pending}>Create account</SubmitButton>
    </form>
  );
}
