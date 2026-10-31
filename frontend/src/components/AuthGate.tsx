import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { setUnauthorizedHandler } from "../api";
import { useTheme } from "../hooks/useTheme";
import { resetClientState } from "../lib/sessionReset";
import { useSession } from "../store/session";
import { AuthScreen } from "./AuthScreen";
import { SpinnerIcon } from "./icons";
import { Button } from "./ui";

// Decides what the page is: nothing yet, the login screen, or the app. The app mounts only for a signed-in user,
// so none of its requests can fire before /me has answered.
export function AuthGate({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  const qc = useQueryClient();
  // The login screen sits outside App, which is what normally applies the theme.
  useTheme();

  useEffect(() => {
    setUnauthorizedHandler(() => useSession.getState().expire());
    void useSession.getState().load();
    return () => setUnauthorizedHandler(null);
  }, []);

  // Runs on sign-out and on session loss alike, after the app has unmounted.
  useEffect(() => {
    if (status === "anonymous") resetClientState(qc);
  }, [status, qc]);

  if (status === "signedIn") return children;
  if (status === "anonymous") return <AuthScreen />;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg p-4 text-text">
      {status === "pending" ? (
        <div role="status" className="text-muted">
          <SpinnerIcon width={24} height={24} className="motion-safe:animate-spin" />
          <span className="sr-only">Loading</span>
        </div>
      ) : (
        <div role="alert" className="flex flex-col items-center gap-3 text-center">
          <p>Could not reach the server.</p>
          <Button variant="secondary" onClick={() => void useSession.getState().load()}>
            Try again
          </Button>
        </div>
      )}
    </main>
  );
}
